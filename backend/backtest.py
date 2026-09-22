"""Walk-forward evaluation for the Premier League Dixon--Coles forecaster.

This deliberately evaluates probabilities against completed scores only.  It
does not use odds, stakes, or any future result when fitting a forecast.
"""
import json
import math
from collections import Counter
from datetime import datetime

from .engine import history
from .models import XI_TUNING_CONFIGS, fit_dixon_coles, predict_1x2
from .playerstats import historical_lineups
from .db import dump, now, set_setting


OUTCOMES = ('home', 'draw', 'away')


def outcome(stats):
    """Return the 1X2 outcome for a finished match's score payload."""
    if stats['hg'] > stats['ag']:
        return 'home'
    if stats['hg'] < stats['ag']:
        return 'away'
    return 'draw'


def completed_matches(connection):
    """Load only usable Premier League results, in their chronological order."""
    rows = connection.execute("""
        SELECT id, home, away, kickoff, stats
        FROM matches
        WHERE competition='E0' AND status='finished'
        ORDER BY kickoff, id
    """).fetchall()
    matches = []
    for row in rows:
        match = dict(row)
        match['stats'] = json.loads(match['stats'])
        if match['stats'].get('hg') is not None and match['stats'].get('ag') is not None:
            matches.append(match)
    return matches


def walk_forward(connection, minimum_samples=40, retrain_days=1):
    """Score strictly pre-kickoff forecasts, optionally sharing a recent fit."""
    if minimum_samples < 1:
        raise ValueError('minimum_samples must be positive')
    if retrain_days < 1:
        raise ValueError('retrain_days must be positive')
    fixtures = completed_matches(connection)
    evaluations = []
    models = {}
    for fixture in fixtures:
        # A model fit is shared only with later fixtures in its interval; its
        # training cutoff remains the interval's first fixture, never a future
        # result. A one-day interval is the fixture-by-fixture default.
        interval = datetime.fromisoformat(fixture['kickoff']).date().toordinal() // retrain_days
        model = models.get(interval)
        if model is None:
            prior = history(connection, fixture['kickoff'])
            if len(prior) < minimum_samples:
                models[interval] = False
                continue
            model = fit_dixon_coles(prior, fixture['kickoff'])
            models[interval] = model
        if model is False:
            continue
        prediction = predict_1x2(model, fixture['home'], fixture['away'])
        if prediction is None:
            continue
        probabilities = prediction['probabilities']
        actual = outcome(fixture['stats'])
        pick = max(OUTCOMES, key=probabilities.__getitem__)
        evaluations.append({
            'id': fixture['id'],
            'kickoff': fixture['kickoff'],
            'actual': actual,
            'pick': pick,
            'correct': pick == actual,
            'probabilities': probabilities,
            'log_loss': -math.log(max(probabilities[actual], 1e-15)),
            'brier': sum((probabilities[key] - (key == actual)) ** 2 for key in OUTCOMES) / len(OUTCOMES),
        })
    return evaluations


def walk_forward_player(connection, minimum_samples=40, retrain_days=1, config=None):
    """Evaluate actual historical XIs with only pre-kickoff player data."""
    fixtures = completed_matches(connection); evaluations = []; models = {}
    for fixture in fixtures:
        features = historical_lineups(connection, fixture['id'], fixture['kickoff'])
        if not features: continue
        interval = datetime.fromisoformat(fixture['kickoff']).date().toordinal() // retrain_days
        model = models.get(interval)
        if model is None:
            prior = history(connection, fixture['kickoff']); train_features = {}
            for item in prior:
                value = historical_lineups(connection, item['id'], item['kickoff'])
                if value: train_features[item['id']] = value
            prior = [item for item in prior if item['id'] in train_features]
            model = fit_dixon_coles(prior, fixture['kickoff'], train_features, version='xi-v2', config=config) if len(prior) >= minimum_samples else False
            models[interval] = model
        if model is False: continue
        prediction = predict_1x2(model, fixture['home'], fixture['away'], features)
        if not prediction: continue
        probabilities = prediction['probabilities']; actual = outcome(fixture['stats']); pick = max(OUTCOMES, key=probabilities.__getitem__)
        evaluations.append({'id': fixture['id'], 'kickoff': fixture['kickoff'], 'actual': actual, 'pick': pick, 'correct': pick == actual, 'probabilities': probabilities, 'log_loss': -math.log(max(probabilities[actual], 1e-15)), 'brier': sum((probabilities[key] - (key == actual)) ** 2 for key in OUTCOMES) / len(OUTCOMES)})
    return evaluations


def summary(evaluations, calibration_bins=10):
    """Aggregate proper scoring rules, accuracy, and simple confidence calibration."""
    if calibration_bins < 1:
        raise ValueError('calibration_bins must be positive')
    total = len(evaluations)
    if not total:
        return {'fixtures': 0, 'accuracy': None, 'log_loss': None, 'brier_score': None, 'outcomes': {}, 'calibration': []}
    counts = Counter(item['actual'] for item in evaluations)
    buckets = [[] for _ in range(calibration_bins)]
    for item in evaluations:
        confidence = item['probabilities'][item['pick']]
        buckets[min(int(confidence * calibration_bins), calibration_bins - 1)].append((confidence, item['correct']))
    calibration = []
    for index, bucket in enumerate(buckets):
        if bucket:
            calibration.append({
                'range': [index / calibration_bins, (index + 1) / calibration_bins],
                'fixtures': len(bucket),
                'mean_confidence': sum(x[0] for x in bucket) / len(bucket),
                'observed_accuracy': sum(x[1] for x in bucket) / len(bucket),
            })
    return {
        'fixtures': total,
        'accuracy': sum(item['correct'] for item in evaluations) / total,
        'log_loss': sum(item['log_loss'] for item in evaluations) / total,
        'brier_score': sum(item['brier'] for item in evaluations) / total,
        'outcomes': {key: counts[key] for key in OUTCOMES},
        'calibration': calibration,
    }


def evaluate_candidate(connection, minimum_samples=40, retrain_days=1):
    """Persist the pre-registered baseline-vs-XI candidate comparison.

    Market validation is deliberately prospective: historical odds are not
    imported, so a candidate cannot become promotion-eligible before 200
    timestamped XI forecasts have accumulated in the local ledger.
    """
    baseline = summary(walk_forward(connection, minimum_samples, retrain_days))
    trials = [(config, summary(walk_forward_player(connection, minimum_samples, retrain_days, config))) for config in XI_TUNING_CONFIGS]
    viable = [trial for trial in trials if trial[1]['fixtures'] and trial[1]['brier_score'] <= baseline['brier_score']]
    selected_config, candidate = min(viable or trials, key=lambda trial: float('inf') if trial[1]['log_loss'] is None else trial[1]['log_loss'])
    prospective = connection.execute("""SELECT COUNT(DISTINCT p.match_id) FROM predictions p
        JOIN models m ON m.id=p.model_id JOIN quotes q ON q.match_id=p.match_id
        WHERE m.metrics LIKE '%xi-v2%' AND p.features LIKE '%confirmed-xi%' AND q.verified=1""").fetchone()[0]
    historical_ok = bool(candidate['fixtures'] >= minimum_samples and baseline['fixtures'] >= minimum_samples
                         and candidate['log_loss'] < baseline['log_loss']
                         and candidate['brier_score'] <= baseline['brier_score'])
    eligible = historical_ok and prospective >= 200
    metrics = {'baseline': baseline, 'candidate': candidate, 'delta': {
        'log_loss': None if not candidate['fixtures'] or not baseline['fixtures'] else candidate['log_loss'] - baseline['log_loss'],
        'brier_score': None if not candidate['fixtures'] or not baseline['fixtures'] else candidate['brier_score'] - baseline['brier_score'],
    }}
    fixtures = candidate['fixtures']
    start = end = None
    if candidate['fixtures']:
        values = walk_forward_player(connection, minimum_samples, retrain_days, selected_config)
        start, end = values[0]['kickoff'], values[-1]['kickoff']
    connection.execute('INSERT INTO model_evaluations(model_version,created_at,started_at,ended_at,fixtures,metrics,benchmark,eligible) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(model_version,started_at,ended_at) DO UPDATE SET created_at=excluded.created_at,fixtures=excluded.fixtures,metrics=excluded.metrics,benchmark=excluded.benchmark,eligible=excluded.eligible',
                       ('xi-v2', now(), start, end, fixtures, dump(metrics), dump({'prospective_xi_fixtures':prospective,'required':200}), int(eligible)))
    set_setting(connection, 'xi_model_config', selected_config)
    return {'model_version': 'xi-v2', 'eligible': eligible, 'historical_ok': historical_ok, 'prospective_xi_fixtures': prospective, 'selected_config': selected_config, **metrics}
