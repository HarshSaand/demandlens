import numpy as np
import pandas as pd
import pytest
from demandlens import make_features,calibrate,summary

def fixture():
    hours=pd.date_range('2024-01-01',periods=900,freq='h')
    return pd.DataFrame({'zone':1,'hour':hours,'count':np.arange(900)})

def test_all_features_precede_day_origin():
    result=make_features(fixture())
    assert (result.latest_observation<result.forecast_origin).all()
    assert np.all(result.lag24==result['count']-24)

def test_future_perturbation_cannot_change_prior_features():
    data=fixture(); changed=data.copy()
    changed.loc[changed.hour>='2024-02-05','count']=999999
    a,b=make_features(data),make_features(changed)
    columns=['lag24','lag168','mean24','mean168']
    assert a.loc[a.hour<'2024-02-05',columns].equals(b.loc[b.hour<'2024-02-05',columns])

def test_missing_hour_rejected():
    with pytest.raises(ValueError): make_features(fixture().drop(index=50))

def test_duplicate_rejected():
    data=fixture()
    with pytest.raises(ValueError): make_features(pd.concat([data,data.iloc[:1]]))

def test_calibration_nonnegative():
    assert calibrate(np.array([5,5]),np.array([0,0]),np.array([10,10]))==0
    assert calibrate(np.array([20,20]),np.array([0,0]),np.array([10,10]))==10

def test_zero_demand_metrics_finite():
    result=summary(np.zeros(3),np.zeros(3),np.zeros(3),np.ones(3))
    assert result['wape']==0 and result['coverage_90']==1
