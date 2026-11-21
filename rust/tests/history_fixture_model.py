"""受控 bar 撮合模型；正式 E 场景与权威故障注入共用输入。"""

def model():
    return dict(model_id='history-sim/bar-batch-known-frontier/1',revision='oracle-1',symbol='TEST',quantity_unit='TEST-UNIT',currency='TEST-CASH',tick_value=1,rd11_policy='controlled-fixture-rd11',rd12_policy='per-leg-source-attribution/1',projection_kind='per_leg',seed='none',fee_profile=dict(reference='controlled-fee/1',role_source='controlled-role-map/1',limit_role='maker',market_role='taker',maker=dict(numerator=1,denominator=100,rounding='ceiling'),taker=dict(numerator=2,denominator=100,rounding='ceiling'),market_slippage_ticks=1,market_slippage_source='controlled-oracle/1'))
