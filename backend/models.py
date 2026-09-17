"""A small, time-decayed Dixon--Coles model for Premier League 1X2 forecasts."""
import math
from collections import Counter
from datetime import datetime
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson

def score_grid(home_goals, away_goals, rho):
    axis=np.arange(max(12,int(max(home_goals,away_goals)+10*math.sqrt(max(home_goals,away_goals)))))
    grid=np.outer(poisson.pmf(axis,home_goals),poisson.pmf(axis,away_goals))
    grid[0,0]*=1-home_goals*away_goals*rho;grid[0,1]*=1+home_goals*rho;grid[1,0]*=1+away_goals*rho;grid[1,1]*=1-rho
    grid=np.maximum(grid,0);return grid/max(grid.sum(),1e-12)

def outcome_probabilities(grid):
    return {'home':float(np.tril(grid,-1).sum()),'draw':float(np.trace(grid)),'away':float(np.triu(grid,1).sum())}

def fit_dixon_coles(records,cutoff,player_features=None):
    teams=sorted({r[k] for r in records for k in ('home','away')})
    if len(teams)<2:return None
    ids={t:i for i,t in enumerate(teams)};n=len(teams)
    home=np.array([ids[r['home']] for r in records]);away=np.array([ids[r['away']] for r in records]);hg=np.array([r['stats']['hg'] for r in records]);ag=np.array([r['stats']['ag'] for r in records])
    ages=np.array([(datetime.fromisoformat(cutoff)-datetime.fromisoformat(r['kickoff'])).total_seconds()/86400 for r in records]);weights=np.exp(-math.log(2)*ages/365)
    player_features = player_features or {}
    use_players = all(r['id'] in player_features for r in records)
    if use_players:
        raw = np.array([[player_features[r['id']][side][key] for r in records for side in ('home','away')] for key in ('xg90','xa90')])
        means = raw.mean(axis=1); scales = np.maximum(raw.std(axis=1), .01)
        home_xg,away_xg=(raw[0,::2]-means[0])/scales[0],(raw[0,1::2]-means[0])/scales[0]
        home_xa,away_xa=(raw[1,::2]-means[1])/scales[1],(raw[1,1::2]-means[1])/scales[1]
    else: means=scales=None
    def loss(p):
        attack=p[:n]-p[:n].mean();defence=p[n:2*n];lam=np.exp(np.clip(p[-3]+attack[home]+defence[away]+p[-2],-3,2.5));mu=np.exp(np.clip(p[-3]+attack[away]+defence[home],-3,2.5));rho=p[-1]
        if use_players:
            beta_xg,beta_xa=p[2*n:2*n+2]
            lam=np.exp(np.clip(np.log(lam)+beta_xg*home_xg+beta_xa*home_xa,-3,2.5));mu=np.exp(np.clip(np.log(mu)+beta_xg*away_xg+beta_xa*away_xa,-3,2.5))
        tau=np.ones(len(records));tau[(hg==0)&(ag==0)]=1-lam[(hg==0)&(ag==0)]*mu[(hg==0)&(ag==0)]*rho;tau[(hg==0)&(ag==1)]=1+lam[(hg==0)&(ag==1)]*rho;tau[(hg==1)&(ag==0)]=1+mu[(hg==1)&(ag==0)]*rho;tau[(hg==1)&(ag==1)]=1-rho
        if np.any(tau<=0):return 1e12
        ll=hg*np.log(lam)-lam-gammaln(hg+1)+ag*np.log(mu)-mu-gammaln(ag+1)+np.log(tau)
        penalty=3*(np.square(attack).sum()+np.square(defence).sum())
        if use_players: penalty += 2*(beta_xg**2+beta_xa**2)
        return float(-(weights*ll).sum()+penalty)
    extra=2 if use_players else 0;initial=np.zeros(2*n+3+extra);initial[-3]=math.log(max(float(ag.mean()),.3));initial[-2]=.15;initial[-1]=-.03
    bounds=[(-1.5,1.5)]*(2*n)+([(-.6,.6)]*2 if use_players else [])+[(-1,1.2),(-.4,.7),(-.12,.08)]
    result=minimize(loss,initial,method='L-BFGS-B',bounds=bounds)
    p=result.x
    model={'teams':teams,'attack':(p[:n]-p[:n].mean()).tolist(),'defence':p[n:2*n].tolist(),'base':float(p[-3]),'home_advantage':float(p[-2]),'rho':float(p[-1]),'appearances':dict(Counter(r[k] for r in records for k in ('home','away'))),'samples':len(records),'converged':bool(result.success)}
    if use_players:model['player_covariates']={'beta_xg':float(p[2*n]),'beta_xa':float(p[2*n+1]),'means':means.tolist(),'scales':scales.tolist()}
    return model

def predict_1x2(model,home,away,lineups=None):
    if not model or home not in model['teams'] or away not in model['teams'] or min(model['appearances'].get(home,0),model['appearances'].get(away,0))<8:return None
    hi,ai=model['teams'].index(home),model['teams'].index(away);log_lam=model['base']+model['attack'][hi]+model['defence'][ai]+model['home_advantage'];log_mu=model['base']+model['attack'][ai]+model['defence'][hi]
    adjustment={'home':0.,'away':0.}
    if model.get('player_covariates') and lineups and set(lineups)=={'home','away'}:
        cov=model['player_covariates']
        for side in ('home','away'):
            adjustment[side]=cov['beta_xg']*((lineups[side]['xg90']-cov['means'][0])/cov['scales'][0])+cov['beta_xa']*((lineups[side]['xa90']-cov['means'][1])/cov['scales'][1])
        log_lam+=adjustment['home'];log_mu+=adjustment['away']
    lam,mu=math.exp(log_lam),math.exp(log_mu)
    return {'home_goals':lam,'away_goals':mu,'probabilities':outcome_probabilities(score_grid(lam,mu,model['rho'])),'lineup_adjustment':adjustment}
