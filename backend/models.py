"""Time-decayed Dixon–Coles, shrinkage count models and chronological evaluation."""
import math
from collections import Counter
from datetime import datetime
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson, nbinom

COUNT_FIELDS = {'corners': ('hc','ac'), 'cards': ('hy','ay'), 'shots': ('hs','as'), 'shots_on_target': ('hst','ast')}

def score_grid(lam, mu, rho):
    axis = np.arange(max(15, int(max(lam, mu) + 12 * math.sqrt(max(lam, mu)))))
    grid = np.outer(poisson.pmf(axis, lam), poisson.pmf(axis, mu))
    grid[0,0] *= 1-lam*mu*rho; grid[0,1] *= 1+lam*rho
    grid[1,0] *= 1+mu*rho; grid[1,1] *= 1-rho
    grid = np.maximum(grid, 0)
    return grid / grid.sum()

def outcome(grid): return [float(np.tril(grid,-1).sum()),float(np.trace(grid)),float(np.triu(grid,1).sum())]

def fit_dc(records, cutoff):
    teams = sorted({r[k] for r in records for k in ('home','away')}); n=len(teams); ids={t:i for i,t in enumerate(teams)}
    hi=np.array([ids[r['home']] for r in records]); ai=np.array([ids[r['away']] for r in records])
    hg=np.array([r['stats']['hg'] for r in records]); ag=np.array([r['stats']['ag'] for r in records])
    ages=np.array([(datetime.fromisoformat(cutoff)-datetime.fromisoformat(r['kickoff'])).total_seconds()/86400 for r in records])
    weights=np.exp(-math.log(2)*ages/365)
    def loss(p):
        attack=p[:n]-p[:n].mean(); defence=p[n:2*n]
        lam=np.exp(np.clip(p[-3]+attack[hi]+defence[ai]+p[-2],-3,2.5))
        mu=np.exp(np.clip(p[-3]+attack[ai]+defence[hi],-3,2.5)); rho=p[-1]
        tau=np.ones(len(records)); z=(hg==0)&(ag==0); tau[z]=1-lam[z]*mu[z]*rho
        z=(hg==0)&(ag==1); tau[z]=1+lam[z]*rho
        z=(hg==1)&(ag==0); tau[z]=1+mu[z]*rho
        z=(hg==1)&(ag==1); tau[z]=1-rho
        if np.any(tau<=0): return 1e8+float(np.maximum(-tau,0).sum()*1e8)
        ll=hg*np.log(lam)-lam-gammaln(hg+1)+ag*np.log(mu)-mu-gammaln(ag+1)+np.log(tau)
        return float(-(weights*ll).sum()+3*(np.square(attack).sum()+np.square(defence).sum()))
    initial=np.zeros(2*n+3);initial[-3]=math.log(max(float(ag.mean()),.3));initial[-2]=.15; initial[-1]=-.03
    result=minimize(loss,initial,method='L-BFGS-B',bounds=[(-1.5,1.5)]*(2*n)+[(-1,1.2),(-.4,.7),(-.12,.08)],options={'maxiter':200})
    p=result.x
    return {'teams':teams,'attack':(p[:n]-p[:n].mean()).tolist(),'defence':p[n:2*n].tolist(),'base':float(p[-3]),'home_adv':float(p[-2]),'rho':float(p[-1]),'counts':dict(Counter([r[k] for r in records for k in ('home','away')])),'converged':bool(result.success)}

def rates(model,home,away):
    if min(model['counts'].get(home,0),model['counts'].get(away,0))<8: return None
    hi=model['teams'].index(home);ai=model['teams'].index(away)
    return (math.exp(model['base']+model['attack'][hi]+model['defence'][ai]+model['home_adv']),math.exp(model['base']+model['attack'][ai]+model['defence'][hi]))

def count_estimate(records,home,away,fields):
    a,b=fields; usable=[r for r in records if r['stats'].get(a) is not None and r['stats'].get(b) is not None]
    if len(usable)<80: return None
    base_h=float(np.mean([r['stats'][a] for r in usable]));base_a=float(np.mean([r['stats'][b] for r in usable]))
    def team(t,own):
        values=[r['stats'][a if (r['home']==t)==own else b] for r in usable if t in (r['home'],r['away'])][-30:]
        if len(values)<8:return None
        return (sum(values)+8*(base_h+base_a)/2)/(len(values)+8)
    hf,ha,af,aa=team(home,True),team(home,False),team(away,True),team(away,False)
    if any(x is None for x in (hf,ha,af,aa)):return None
    mean=max(.1,math.sqrt(hf*aa)*2*base_h/max(.1,base_h+base_a)+math.sqrt(af*ha)*2*base_a/max(.1,base_h+base_a))
    totals=np.array([r['stats'][a]+r['stats'][b] for r in usable]); variance=float(totals.var()); avg=float(totals.mean())
    dispersion=avg*avg/(variance-avg) if variance>avg+0.1 else 10000
    return {'mean':mean,'dispersion':dispersion,'samples':len(usable)}

def form_factor(records,team):
    values=[(r['stats']['hg'] if r['home']==team else r['stats']['ag']) for r in records if team in (r['home'],r['away'])][-5:]
    return min(1.15,max(.85,(sum(values)+7.5)/(len(values)*1.5+7.5)))

def evaluate(records,cutoff):
    # Match-date holdout measures generalisation, not a reconstructed historical betting run.
    split=max(80,int(len(records)*.8)); train=records[:split]; test=records[split:]
    if len(test)<30: return {'status':'Insufficient holdout data','samples':0},'baseline'
    boundary=test[0]['kickoff']; train=[r for r in train if r['kickoff']<boundary]
    model=fit_dc(train,boundary); metrics={k:[] for k in ('baseline','form')}; bins=[{'count':0,'predicted':0.,'actual':0.} for _ in range(10)]
    count_errors={k:[] for k in COUNT_FIELDS}; correct=0;brier=[];market_ll=[]
    for r in test:
        rm=rates(model,r['home'],r['away'])
        if rm is None:continue
        actual=0 if r['stats']['hg']>r['stats']['ag'] else 1 if r['stats']['hg']==r['stats']['ag'] else 2
        for candidate in metrics:
            l,m=rm
            if candidate=='form':l*=form_factor(train,r['home']);m*=form_factor(train,r['away'])
            p=outcome(score_grid(l,m,model['rho'])); metrics[candidate].append(-math.log(max(1e-12,p[actual])))
            if candidate=='baseline':
                correct+=int(np.argmax(p)==actual);brier.append(sum((x-int(i==actual))**2 for i,x in enumerate(p)))
                for i,x in enumerate(p):
                    cell=bins[min(9,int(x*10))];cell['count']+=1;cell['predicted']+=x;cell['actual']+=int(i==actual)
        op=r['stats'].get('closing_1x2')
        if op:
            probs=np.array([1/x for x in op]);probs/=probs.sum();market_ll.append(-math.log(max(1e-12,probs[actual])))
        for k,fields in COUNT_FIELDS.items():
            est=count_estimate(train,r['home'],r['away'],fields)
            if est and all(r['stats'].get(f) is not None for f in fields):count_errors[k].append(abs(est['mean']-sum(r['stats'][f] for f in fields)))
    n=len(metrics['baseline'])
    selected='form' if n>=50 and np.mean(metrics['form'])+.01<np.mean(metrics['baseline']) else 'baseline'
    return {'status':'Chronological holdout · match-date split','samples':n,'train_samples':len(train),'split_at':boundary,'log_loss':{k:float(np.mean(v)) if v else None for k,v in metrics.items()},'selected':selected,'accuracy':correct/n if n else None,'brier':float(np.mean(brier)) if brier else None,'market_log_loss':float(np.mean(market_ll)) if market_ll else None,'market_samples':len(market_ll),'calibration':[{'count':b['count'],'predicted':b['predicted']/b['count'],'actual':b['actual']/b['count']} for b in bins if b['count']],'count_mae':{k:{'mae':float(np.mean(v)) if v else None,'samples':len(v)} for k,v in count_errors.items()},'note':'Archive statistics split by match date. This is predictive validation, not point-in-time profit evidence; market benchmark uses available closing prices.'},selected

def predict(model,records,home,away):
    rm=rates(model['dc'],home,away)
    if rm is None:return None
    l,m=rm
    if model['selected']=='form':l*=form_factor(records,home);m*=form_factor(records,away)
    grid=score_grid(l,m,model['dc']['rho']);probs=outcome(grid)
    picks=[{'market':'1x2','selection':s,'line':None,'player':'','probability':p,'push':0} for s,p in zip(['home','draw','away'],probs)]
    totals=np.add.outer(np.arange(len(grid)),np.arange(len(grid)))
    for line in [0.5,1.5,2,2.5,3,3.5,4.5]:
        for side in ['over','under']:
            p=float(grid[totals>line if side=='over' else totals<line].sum())
            picks.append(dict(market='goals',selection=side,line=line,player='',probability=p,push=float(grid[totals==line].sum())))
    yes=float(grid[1:,1:].sum())
    picks.extend([dict(market='btts',selection=s,line=None,player='',probability=p,push=0) for s,p in [('yes',yes),('no',1-yes)]])
    counts={}
    for kind,fields in COUNT_FIELDS.items():
        est=count_estimate(records,home,away,fields)
        if not est:continue
        counts[kind]=est;dist=nbinom(est['dispersion'],est['dispersion']/(est['dispersion']+est['mean']))
        lines={'corners':[8.5,9.5,10.5,11.5],'cards':[2.5,3.5,4.5,5.5],'shots':[19.5,21.5,23.5,25.5],'shots_on_target':[6.5,7.5,8.5,9.5]}[kind]
        for line in lines:
            p=float(dist.sf(line))
            picks.extend([dict(market=kind,selection=s,line=line,player='',probability=v,push=0) for s,v in [('over',p),('under',1-p)]])
    scores=sorted([{'home':i,'away':j,'probability':float(grid[i,j])} for i in range(7) for j in range(7)],key=lambda s:-s['probability'])[:8]
    return {'home_goals':l,'away_goals':m,'outcomes':probs,'scorelines':scores,'counts':counts,'selections':picks,'quality':'supported','player_status':'Requires verified player history and expected minutes','sample_min':min(model['dc']['counts'][home],model['dc']['counts'][away])}

