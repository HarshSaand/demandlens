"""Day-ahead count forecasting on real TLC records with strict origin availability."""
import os
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:
    os.environ[name]='2'
import argparse
import hashlib
import json
import platform
import time
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb
import sklearn
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_pinball_loss
import requests
import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
OUT=ROOT/'outputs'
HOLIDAYS=pd.to_datetime(['2024-01-01','2024-01-15','2024-02-19','2024-05-27','2024-06-19'])
FEATURES=['zone','hour_of_day','day_of_week','month','is_holiday','lag24','lag48','lag168','lag336','mean24','mean168']

def sha256(path):
    digest=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1048576),b''): digest.update(block)
    return digest.hexdigest()

def fetch(month):
    DATA.mkdir(exist_ok=True)
    filename=f'yellow_tripdata_2024-{month:02}.parquet'
    path=DATA/filename
    url=f'https://d37ci6vzurychx.cloudfront.net/trip-data/{filename}'
    if not path.exists():
        tmp=path.with_suffix('.partial')
        with requests.get(url,stream=True,timeout=120) as r:
            r.raise_for_status()
            with tmp.open('wb') as f:
                for b in r.iter_content(1048576): f.write(b)
        tmp.rename(path)
    return path,url

def prepare(top_zones=30):
    if not 1 <= top_zones <= 263: raise ValueError('zones must be between 1 and 263')
    OUT.mkdir(exist_ok=True)
    con=duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET memory_limit='1GB'")
    aggregate=[]; provenance=[]
    for month in range(1,7):
        print(f'Fetching/aggregating real TLC 2024-{month:02}',flush=True)
        path,url=fetch(month)
        start=f'2024-{month:02}-01'
        stop=f'2024-{month+1:02}-01'
        source=str(path).replace("'","''")
        where=f"tpep_pickup_datetime >= TIMESTAMP '{start}' AND tpep_pickup_datetime < TIMESTAMP '{stop}' AND PULocationID BETWEEN 1 AND 263"
        rows=con.execute(f"SELECT count(*) FROM read_parquet('{source}')").fetchone()[0]
        frame=con.execute(f"SELECT date_trunc('hour', tpep_pickup_datetime) AS hour, PULocationID AS zone, count(*) AS count FROM read_parquet('{source}') WHERE {where} GROUP BY 1,2").df()
        provenance.append(dict(month=month,url=url,sha256=sha256(path),source_rows=rows,
            valid_pickups=int(frame['count'].sum()),excluded_wrong_month_or_unknown_zone=int(rows-frame['count'].sum())))
        aggregate.append(frame)
    all_counts=pd.concat(aggregate,ignore_index=True)
    train_counts=all_counts[all_counts.hour<'2024-04-01'].groupby('zone')['count'].sum()
    zones=train_counts.nlargest(top_zones).index.sort_values().tolist()
    grid=pd.MultiIndex.from_product([zones,pd.date_range('2024-01-01','2024-07-01',freq='h',inclusive='left')],names=['zone','hour'])
    dense=all_counts.set_index(['zone','hour']).reindex(grid,fill_value=0).reset_index()
    dense.to_parquet(DATA/'hourly.parquet',index=False)
    report=dict(dataset='NYC TLC 2024 yellow taxi January-June',months=provenance,
        source_rows=sum(p['source_rows'] for p in provenance),
        valid_pickups=sum(p['valid_pickups'] for p in provenance),selected_zones=zones,
        selected_zone_count=top_zones,zone_selection='Top zones by pickup count in January-March only',
        selected_zone_pickups=int(dense['count'].sum()),hourly_rows=len(dense),
        selected_zone_share=float(dense['count'].sum()/all_counts['count'].sum()),
        sha256_hourly=sha256(DATA/'hourly.parquet'),
        limitations=['Only yellow taxis, not all NYC transport demand',
            'Zero filled means zero recorded pickups, not verified zero true demand',
            'Provider timestamps treated as local wall clock, daylight-saving ambiguity not resolved',
            'TLC does not guarantee accuracy or completeness of source records'])
    (OUT/'provenance.json').write_text(json.dumps(report,indent=2))

def make_features(frame):
    frame=frame.sort_values(['zone','hour']).copy()
    if frame.duplicated(['zone','hour']).any(): raise ValueError('Duplicate zone-hour')
    for _,group in frame.groupby('zone'):
        if not group.hour.diff().dropna().eq(pd.Timedelta(hours=1)).all():
            raise ValueError('Complete hourly grid required')
    for lag in [24,48,168,336,504,672]:
        frame[f'lag{lag}']=frame.groupby('zone')['count'].shift(lag)
    for window in [24,168]:
        frame[f'mean{window}']=frame.groupby('zone')['count'].transform(lambda s:s.shift(24).rolling(window).mean())
    frame['seasonal_median']=frame[['lag168','lag336','lag504','lag672']].median(axis=1)
    frame['hour_of_day']=frame.hour.dt.hour
    frame['day_of_week']=frame.hour.dt.dayofweek
    frame['month']=frame.hour.dt.month
    frame['is_holiday']=frame.hour.dt.normalize().isin(HOLIDAYS).astype(int)
    frame['forecast_origin']=frame.hour.dt.normalize()
    frame['latest_observation']=frame.hour-pd.Timedelta(hours=24)
    if not (frame.latest_observation<frame.forecast_origin).all():
        raise ValueError('Future data entered day-ahead features')
    return frame.dropna().reset_index(drop=True)

def calibrate(y,lower,upper,alpha=.1):
    if len(y)==0: raise ValueError('Empty calibration window')
    residual=np.maximum.reduce([lower-y,y-upper,np.zeros(len(y))])
    level=min(1.,np.ceil((len(y)+1)*(1-alpha))/len(y))
    return float(np.quantile(residual,level,method='higher'))

def summary(y,pred,lo=None,hi=None):
    result=dict(n=len(y),mae=float(np.abs(y-pred).mean()),
        wape=float(np.abs(y-pred).sum()/np.maximum(y.sum(),1)))
    if lo is not None:
        result.update(coverage_90=float(((y>=lo)&(y<=hi)).mean()),mean_width=float((hi-lo).mean()))
    return result

def fit(train,objective='poisson',alpha=.5):
    model=LGBMRegressor(objective=objective,alpha=alpha,n_estimators=180,
        learning_rate=.05,num_leaves=31,min_child_samples=100,reg_lambda=2,
        n_jobs=2,random_state=42,verbosity=-1)
    model.fit(train[FEATURES],train['count'],categorical_feature=['zone'])
    return model

def run():
    started=time.time()
    OUT.mkdir(exist_ok=True)
    (ROOT/'checkpoints').mkdir(exist_ok=True)
    frame=make_features(pd.read_parquet(DATA/'hourly.parquet'))
    report=dict(protocol='Two frozen-hyperparameter rolling-origin folds. Day-ahead calendar-day forecasts; no same-day counts.',
        hourly_data_sha256=sha256(DATA/'hourly.parquet'),python=platform.python_version(),
        features=FEATURES,seed=42,threads=2,platform=platform.platform(),folds={},
        limitations=['One six-month yellow-taxi benchmark and train-selected busiest zones',
            'No live operational cost savings or staffing validation',
            'Split residual calibration under temporal dependence has no unconditional coverage guarantee',
            'Lag features refreshed daily with newly available historical observations; no within-day refresh',
            'One training seed; no training uncertainty intervals'])
    predictions=[]
    for label,train_end,dev_end,cal_end,test_end in [
        ('may','2024-04-01','2024-04-15','2024-05-01','2024-06-01'),
        ('june','2024-05-01','2024-05-15','2024-06-01','2024-07-01')]:
        train=frame[frame.hour<train_end]
        dev=frame[(frame.hour>=train_end)&(frame.hour<dev_end)]
        calibration=frame[(frame.hour>=dev_end)&(frame.hour<cal_end)]
        test=frame[(frame.hour>=cal_end)&(frame.hour<test_end)]
        print(f'{label}: train {len(train)}, dev {len(dev)}, calibration {len(calibration)}, test {len(test)}',flush=True)
        point=fit(train)
        lower=fit(train,'quantile',.05)
        upper=fit(train,'quantile',.95)
        # Sort crossed quantiles before calibration and evaluation consistently.
        cl,cu=np.sort(np.vstack([lower.predict(calibration[FEATURES]),upper.predict(calibration[FEATURES])]),axis=0)
        adjustment=calibrate(calibration['count'].to_numpy(),cl,cu)
        raw_lo,raw_hi=np.sort(np.vstack([lower.predict(test[FEATURES]),upper.predict(test[FEATURES])]),axis=0)
        lo=np.maximum(0,raw_lo-adjustment); hi=raw_hi+adjustment
        pred=point.predict(test[FEATURES]); y=test['count'].to_numpy()
        models={'same_hour_last_week':summary(y,test.lag168.to_numpy()),
            'four_week_seasonal_median':summary(y,test.seasonal_median.to_numpy()),
            'lightgbm_count':summary(y,pred,lo,hi)}
        train_scale=train.assign(error=np.abs(train['count']-train.lag168)).groupby('zone').error.mean()
        zone_reports=[]
        for zone,index in test.groupby('zone').indices.items():
            scale=float(train_scale.loc[zone])
            item=summary(y[index],pred[index],lo[index],hi[index])
            item.update(zone=int(zone),mase=float(item['mae']/scale) if scale>0 else None)
            zone_reports.append(item)
        low_zones=train.groupby('zone')['count'].mean().nsmallest(max(1,train.zone.nunique()//4)).index
        masks={'peak_hours':test.hour_of_day.between(16,19).to_numpy(),
            'nonpeak_hours':(~test.hour_of_day.between(16,19)).to_numpy(),
            'lower_volume_selected_zones':test.zone.isin(low_zones).to_numpy(),
            'holiday':test.is_holiday.to_numpy()==1,
            'first_half':(test.hour<pd.Timestamp(cal_end)+pd.Timedelta(days=15)).to_numpy(),
            'second_half':(test.hour>=pd.Timestamp(cal_end)+pd.Timedelta(days=15)).to_numpy()}
        slices={key:summary(y[m],pred[m],lo[m],hi[m]) for key,m in masks.items() if m.any()}
        report['folds'][label]=dict(train_rows=len(train),development_rows=len(dev),
            calibration_rows=len(calibration),test_rows=len(test),train_end_exclusive=train_end,
            calibration_start=dev_end,test_start=cal_end,test_end_exclusive=test_end,
            calibration_adjustment=adjustment,
            calibration_raw_coverage=float(((calibration['count']>=cl)&(calibration['count']<=cu)).mean()),
            raw_test_coverage=float(((y>=raw_lo)&(y<=raw_hi)).mean()),
            raw_test_mean_width=float((raw_hi-raw_lo).mean()),
            quantile_pinball_05=float(mean_pinball_loss(y,raw_lo,alpha=.05)),
            quantile_pinball_95=float(mean_pinball_loss(y,raw_hi,alpha=.95)),
            development_count=summary(dev['count'].to_numpy(),point.predict(dev[FEATURES])),
            models=models,zone_reports=zone_reports,slices=slices)
        predictions.append(test[['hour','zone','count']].assign(pred=pred,lo=lo,hi=hi,fold=label))
        joblib.dump(dict(point=point,lower=lower,upper=upper,adjustment=adjustment,features=FEATURES),ROOT/f'checkpoints/{label}.joblib')
        report['folds'][label]['checkpoint_sha256']=sha256(ROOT/f'checkpoints/{label}.joblib')
    report['elapsed_seconds']=time.time()-started
    (OUT/'evaluation.json').write_text(json.dumps(report,indent=2))
    pred=pd.concat(predictions,ignore_index=True)
    pred.to_parquet(DATA/'predictions.parquet',index=False)
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for offset,(label,fold) in enumerate(report['folds'].items()):
        keys=list(fold['models']); vals=[fold['models'][k]['mae'] for k in keys]
        axes[0].bar(np.arange(3)+offset*.35,vals,width=.35,label=label)
    axes[0].set_xticks(np.arange(3)+.175,['last week','seasonal median','boosted count'])
    axes[0].set(ylabel='MAE: pickups per zone-hour',title='Two rolling-origin held-out months'); axes[0].legend()
    for label,fold in report['folds'].items():
        axes[1].plot(['raw','calibrated'],[fold['raw_test_coverage'],fold['models']['lightgbm_count']['coverage_90']],marker='o',label=label)
    axes[1].axhline(.9,color='black',linestyle='--',label='nominal 90%')
    axes[1].set(ylabel='Empirical test coverage',title='Intervals under temporal shift'); axes[1].legend()
    fig.tight_layout();fig.savefig(OUT/'forecast-evaluation.png',dpi=160)
    print(json.dumps({k:v['models'] for k,v in report['folds'].items()},indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['prepare','run'])
    parser.add_argument('--zones',type=int,default=30)
    args=parser.parse_args()
    if args.command=='prepare': prepare(args.zones)
    else: run()
