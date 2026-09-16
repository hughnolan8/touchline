"""Prediction snapshots, comparable prices, and transactional paper portfolios."""
import json
import math
import sqlite3
from datetime import datetime,timedelta
from collections import defaultdict
from .db import COMPETITIONS,connect,rows,now,dump,setting,set_setting
from .models import predict,COUNT_FIELDS

def seconds(a,b): return (datetime.fromisoformat(a)-datetime.fromisoformat(b)).total_seconds()

def history(c,competition,cutoff):
    # Read the last observed state before the model cutoff, not today's mutable match row.
    result=rows(c,"""SELECT m.id,m.home,m.away,o.payload FROM matches m JOIN observations o ON o.match_id=m.id
        WHERE m.competition=? AND o.id=(SELECT o2.id FROM observations o2 WHERE o2.match_id=m.id AND o2.observed_at<=? ORDER BY o2.observed_at DESC,o2.id DESC LIMIT 1)""",(competition,cutoff))
    output=[]
    for r in result:
        state=json.loads(r.pop('payload'))
        if state.get('status')!='finished' or state.get('kickoff','9999')>=cutoff:continue
        r.update(kickoff=state['kickoff'],stats=state['stats'])
        if all(r['stats'].get(k) is not None for k in ('hg','ag')):output.append(r)
    unique={}
    for r in output:
        key=(r['home'],r['away'],r['kickoff'][:10])
        if key not in unique or sum(v is not None for v in r['stats'].values())>sum(v is not None for v in unique[key]['stats'].values()):unique[key]=r
    return sorted(unique.values(),key=lambda r:r['kickoff'])


def generate_predictions(at=None):
    at=at or now();limit=(datetime.fromisoformat(at)+timedelta(days=14)).isoformat();count=0
    with connect() as c:
        models={r['competition']:r for r in rows(c,'SELECT id,competition,cutoff FROM models WHERE id IN (SELECT MAX(id) FROM models GROUP BY competition)')}
        model_payloads={}
        model_histories={}
        for match in rows(c,"SELECT * FROM matches WHERE status='scheduled' AND kickoff>? AND kickoff<?",(at,limit)):
            model=models.get(match['competition'])
            if not model or model['cutoff']>at:continue
            previous=c.execute('SELECT model_id,kickoff,created_at FROM predictions WHERE match_id=? ORDER BY id DESC LIMIT 1',(match['id'],)).fetchone()
            if (previous and previous['model_id']==model['id'] and previous['kickoff']==match['kickoff']
                    and previous['created_at']>=match['observed_at'] and 0<=seconds(at,previous['created_at'])<86400):
                continue
            if model['id'] not in model_payloads:
                model_payloads[model['id']]=json.loads(c.execute('SELECT payload FROM models WHERE id=?',(model['id'],)).fetchone()[0])
            data=model_payloads[model['id']]
            if model['id'] not in model_histories:model_histories[model['id']]=history(c,match['competition'],model['cutoff'])
            records=model_histories[model['id']]
            prediction=predict(data,records,match['home'],match['away'],match['kickoff'],json.loads(match['stats']))
            if not prediction:continue
            features={'home':match['home'],'away':match['away'],'stats':json.loads(match['stats']),'training_cutoff':model['cutoff'],'forecast_date':at[:10]}
            c.execute('INSERT OR IGNORE INTO predictions(match_id,model_id,created_at,kickoff,payload,features) VALUES(?,?,?,?,?,?)',(match['id'],model['id'],at,match['kickoff'],dump(prediction),dump(features)))
            count+=1
    return count

def latest_matches(c,at=None):
    at=at or now()
    result=rows(c,"SELECT m.*,h.name home_name,a.name away_name FROM matches m JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE m.kickoff>=? AND m.kickoff<? ORDER BY m.kickoff LIMIT 600",((datetime.fromisoformat(at)-timedelta(days=1)).isoformat(),(datetime.fromisoformat(at)+timedelta(days=14)).isoformat()))
    for m in result:
        p=c.execute('SELECT id,model_id,kickoff,created_at,payload FROM predictions WHERE match_id=? ORDER BY id DESC LIMIT 1',(m['id'],)).fetchone()
        m['stats']=json.loads(m['stats']);m['prediction']=json.loads(p['payload']) if p and p['kickoff']==m['kickoff'] else None
        m['prediction_id']=p['id'] if p else None;m['model_id']=p['model_id'] if p else None
        m['prediction_at']=p['created_at'] if p else None
        m['competition_name']=COMPETITIONS[m['competition']]
    return result

def matching_selection(pred,q):
    return next((s for s in pred['selections'] if (s['market'],s['selection'],s['line'],s.get('player',''))==(q['market'],q['selection'],q['line'],q['player'])),None)

def quote_key(q):return (q['match_id'],q['market'],q['selection'],q['line'],q['player'],q['rules'],q['bookmaker'])

def expected_return(p,odds,push=0):return p*(odds-1)-(1-p-push)
def fair_odds(p,push=0):return (1-push)/p if p>0 else None

def devig(quotes):
    required={'home','draw','away'} if quotes[0]['market']=='1x2' else {'yes','no'} if quotes[0]['market']=='btts' else {'over','under'}
    by={q['selection']:q for q in quotes}
    if set(by)!=required:return {}
    # Only complete contemporaneous sets are meaningful bookmaker probability benchmarks.
    dates=[q['quoted_at'] for q in quotes]
    if any(t is None for t in dates) or abs(seconds(max(dates),min(dates)))>60:return {}
    margin=sum(1/q['odds'] for q in by.values())
    return {s:1/q['odds']/margin for s,q in by.items()}

def opportunities(c,at=None,include_indicative=False):
    at=at or now();matches={m['id']:m for m in latest_matches(c,at) if m['status']=='scheduled' and m['kickoff']>at and m['prediction']}
    quotes=rows(c,"SELECT q.* FROM quotes q JOIN matches m ON m.id=q.match_id WHERE m.status='scheduled' AND m.kickoff>?         AND q.id IN (SELECT MAX(id) FROM quotes GROUP BY match_id,market,selection,line,player,rules,bookmaker) ORDER BY q.id",(at,))
    latest={quote_key(q):q for q in quotes};groups=defaultdict(list)
    for q in latest.values():groups[(q['match_id'],q['market'],q['line'],q['player'],q['rules'],q['bookmaker'])].append(q)
    probabilities={}
    for group in groups.values():
        for s,p in devig(group).items():probabilities[next(q['id'] for q in group if q['selection']==s)]=p
    result=[]
    for q in latest.values():
        m=matches.get(q['match_id'])
        if not m:continue
        s=matching_selection(m['prediction'],q)
        if not s:continue
        reasons=[]
        if q['rules']!='90min':reasons.append('Unsupported settlement rules')
        if q['id'] not in probabilities:reasons.append('Incomplete or asynchronous bookmaker market')
        if not m['time_confirmed']:reasons.append('Kickoff time unconfirmed')
        if not q['verified'] or not q['quoted_at']:reasons.append('Quote time unverified')
        elif not 0<=seconds(at,q['quoted_at'])<=900:reasons.append('Stale quote')
        if seconds(at,q['collected_at'])<0:reasons.append('Future observation')
        if seconds(at,m['prediction_at'])>86400*7:reasons.append('Prediction older than seven days')
        if q['market'].startswith('player_'):reasons.append('Player model not yet independently validated')
        if reasons and not include_indicative:continue
        p=s['probability'];push=s.get('push',0)
        result.append({**q,'home_name':m['home_name'],'away_name':m['away_name'],'competition':m['competition'],'competition_name':m['competition_name'],'kickoff':m['kickoff'],'prediction_id':m['prediction_id'],'model_id':m['model_id'],'probability':p,'push':push,'fair_odds':fair_odds(p,push),'edge':expected_return(p,q['odds'],push),'market_probability':probabilities.get(q['id']),'eligible':not reasons,'reasons':reasons,'age_minutes':seconds(at,q['quoted_at'])/60 if q['quoted_at'] else None,'sample_size':m['prediction']['sample_min']})
    best={}
    for o in result:
        key=(o['match_id'],o['market'],o['selection'],o['line'],o['player'],o['rules'],o['eligible'])
        if key not in best or o['odds']>best[key]['odds']:best[key]=o
    return sorted(best.values(),key=lambda o:-o['edge'])

def portfolios(c):
    output=[]
    for name in ['automatic']:
        bets=rows(c,'SELECT b.*,h.name home_name,a.name away_name,m.competition,m.kickoff FROM bets b JOIN matches m ON m.id=b.match_id JOIN teams h ON h.id=m.home JOIN teams a ON a.id=m.away WHERE portfolio=? ORDER BY b.id DESC',(name,))
        for b in bets:
            b['snapshot']=json.loads(b['snapshot']);snap=b['snapshot'];b['closing_price_change']=None
            closing=c.execute('''SELECT odds FROM quotes WHERE match_id=? AND market=? AND selection=? AND line IS ? AND player=? AND rules=? AND bookmaker=? AND verified=1 AND quoted_at<? AND collected_at<? AND quoted_at>=? ORDER BY quoted_at DESC,id DESC LIMIT 1''',(b['match_id'],snap['market'],snap['selection'],snap['line'],snap['player'],snap['rules'],snap['bookmaker'],b['kickoff'],b['kickoff'],(datetime.fromisoformat(b['kickoff'])-timedelta(minutes=15)).isoformat())).fetchone()
            if closing and b['kickoff']<now():b['closing_price_change']=snap['odds']/closing[0]-1
        settled=[b for b in bets if b['status'] not in ('open','review')];risked=[b for b in settled if b['status']!='void'];profit=sum(b['profit'] or 0 for b in settled);staked=sum(b['stake'] for b in risked);reserved=sum(b['stake'] for b in bets if b['status'] in ('open','review'))
        balance=1000+profit;wins=sum(b['status']=='won' for b in risked);n=len(risked)
        equity=1000;peak=1000;drawdown=0;curve=[{'date':'Start','equity':1000}]
        for b in sorted(settled,key=lambda x:x['settled_at']):
            equity+=b['profit'] or 0;peak=max(peak,equity);drawdown=max(drawdown,(peak-equity)/peak);curve.append({'date':b['settled_at'],'equity':round(equity,2)})
        returns=[(b['profit'] or 0)/b['stake'] for b in risked]
        roi_ci=None
        if n>=2:
            avg=sum(returns)/n;sd=math.sqrt(sum((v-avg)**2 for v in returns)/(n-1));roi_ci=[avg-1.96*sd/math.sqrt(n),avg+1.96*sd/math.sqrt(n)]
        output.append(dict(name=name,balance=round(balance,2),available=round(balance-reserved,2),reserved=round(reserved,2),profit=round(profit,2),roi=profit/staked if staked else None,roi_ci=roi_ci,win_rate=wins/n if n else None,settled=n,open=sum(b['status'] in ('open','review') for b in bets),drawdown=drawdown,curve=curve,bets=bets))
    return output

def size_stake(opportunity,account,config,portfolio='automatic'):
    bankroll=max(0,account['balance']);available=max(0,account['available'])
    if config.get('stake_mode','flat')=='flat':
        requested=config['stake'];mode='flat';kelly=0
    else:
        p=opportunity['probability'];push=opportunity.get('push',0);b=opportunity['odds']-1
        # Maximise expected log growth with a push returning the stake unchanged.
        kelly=max(0,expected_return(p,opportunity['odds'],push)/(b*(1-push))) if b>0 and push<1 else 0
        requested=bankroll*kelly*config.get('kelly_fraction',.25);mode='kelly'
    limit=available
    if portfolio=='automatic':
        limit=min(limit,max(0,bankroll*config['max_exposure']-account['reserved']))
        limit=min(limit,bankroll*config.get('max_bet_fraction',.02))
    stake=math.floor((min(requested,limit)+1e-9)*100)/100
    if mode=='flat' and stake<requested:stake=0
    if stake<config.get('min_stake',1):stake=0
    return dict(stake=stake,mode=mode,full_kelly=kelly,kelly_fraction=config.get('kelly_fraction',.25),bankroll=bankroll,uncapped_stake=requested,cap=limit)

def place_bet(c,quote_id,portfolio='automatic',at=None):
    at=at or now();config=setting(c,'strategy')
    # IMMEDIATE transaction is acquired by callers before checking funds and duplicates.
    opportunity=next((o for o in opportunities(c,at) if o['id']==quote_id),None)
    if not opportunity:raise ValueError('Price is stale, no longer best, or lacks a supported prediction / confirmed kickoff')
    if portfolio=='automatic':
        minutes=seconds(opportunity['kickoff'],at)/60
        if not config['enabled'] or not config['window_end']<=minutes<=config['window_start'] or opportunity['edge']<config['min_edge']:raise ValueError('Outside automatic strategy rules')
        if opportunity['age_minutes']>config['max_quote_age']:raise ValueError('Quote exceeds strategy age limit')
    account=next(p for p in portfolios(c) if p['name']==portfolio);sizing=size_stake(opportunity,account,config,portfolio);stake=sizing['stake']
    if stake<=0:raise ValueError('Stake falls below the minimum or available bankroll/exposure limit')
    if account['available']<stake:raise ValueError('Insufficient available virtual funds')
    if portfolio=='automatic' and account['reserved']+stake>account['balance']*config['max_exposure']:raise ValueError('Automatic exposure limit reached')
    snapshot={**opportunity,'strategy':config,'staking':sizing,'rules_description':'90 minutes plus stoppage time; cards = yellow cards only; player markets require verified participation'}
    try:
        cur=c.execute('INSERT INTO bets(portfolio,match_id,quote_id,prediction_id,created_at,stake,snapshot) VALUES(?,?,?,?,?,?,?)',(portfolio,opportunity['match_id'],quote_id,opportunity['prediction_id'],at,stake,dump(snapshot)))
    except sqlite3.IntegrityError:raise ValueError('This paper bet or automatic fixture has already been recorded')
    return cur.lastrowid


def resolve_selection(snapshot,stats):
    kind=snapshot['market'];selection=snapshot['selection']
    if kind=='1x2':
        if stats.get('hg') is None or stats.get('ag') is None:return None
        result='home' if stats['hg']>stats['ag'] else 'away' if stats['ag']>stats['hg'] else 'draw'
        return 'won' if result==selection else 'lost'
    if kind=='btts':
        if stats.get('hg') is None or stats.get('ag') is None:return None
        yes=stats['hg']>0 and stats['ag']>0
        return 'won' if yes==(selection=='yes') else 'lost'
    if kind.startswith('player_'):
        player=next((p for p in stats.get('player_results',[]) if p['player']==snapshot['player']),None)
        if not player or player.get('participated') is None:return None
        if not player['participated']:return 'void'
        value=player.get(kind.removeprefix('player_'))
    else:
        fields=('hg','ag') if kind=='goals' else COUNT_FIELDS.get(kind)
        if not fields or any(stats.get(k) is None for k in fields):return None
        value=sum(stats[k] for k in fields)
    if value is None:return None
    if value==snapshot['line']:return 'push'
    return 'won' if (value>snapshot['line'])==(selection=='over') else 'lost'

def settle(at=None):
    at=at or now();count=0
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for b in rows(c,"SELECT b.*,m.status match_status,m.stats,m.kickoff FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.status IN ('open','review')"):
            if b['match_status']=='cancelled':result='void'
            elif b['match_status']=='finished' and b['kickoff']<at:result=resolve_selection(json.loads(b['snapshot']),json.loads(b['stats']))
            else:continue
            if result is None:
                c.execute("UPDATE bets SET status='review',reason='Final result lacks required market statistics; awaiting verified data' WHERE id=?",(b['id'],));continue
            snap=json.loads(b['snapshot']);profit=round(b['stake']*(snap['odds']-1),2) if result=='won' else -b['stake'] if result=='lost' else 0
            c.execute('UPDATE bets SET status=?,profit=?,settled_at=?,reason=? WHERE id=?',(result,profit,at,'Settled using verified full-time data',b['id']));count+=1
    return count
