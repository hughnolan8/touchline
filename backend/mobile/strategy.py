"""Validated automatic simulation settings."""
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Strategy(BaseModel):
    enabled:bool=True
    stake_mode:Literal['flat','kelly']='kelly'
    kelly_fraction:float=Field(default=.25,gt=0,le=1,allow_inf_nan=False)
    max_bet_fraction:float=Field(default=.02,gt=0,le=.10,allow_inf_nan=False)
    min_stake:float=Field(default=1,ge=.01,le=100,multiple_of=.01,allow_inf_nan=False)
    stake:float=Field(default=10,gt=0,le=1000,multiple_of=0.01,allow_inf_nan=False)
    min_edge:float=Field(default=.05,ge=0,le=1,allow_inf_nan=False)
    max_exposure:float=Field(default=.1,gt=0,le=1,allow_inf_nan=False)
    max_quote_age:int=Field(default=15,ge=1,le=15)
    window_start:int=Field(default=60,ge=2,le=1440)
    window_end:int=Field(default=15,ge=1,le=1439)
    @model_validator(mode='after')
    def valid_window(self):
        if self.window_start<=self.window_end:raise ValueError('Window start must exceed window end')
        return self
