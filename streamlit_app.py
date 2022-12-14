import streamlit as st
import pandas as pd
import json
from snowflake.snowpark import Session
import snowflake.snowpark.functions as F
from snowflake.snowpark.functions import call_udf, col, lit

import altair as alt
import plotly.graph_objects as go
import datetime

# @st.experimental_singleton
def init_connection():
    with open('creds.json') as f:
        connection_parameters = json.load(f)

    return Session.builder.configs(connection_parameters).create()

session = init_connection()

if not 'n_periods_past' in st.session_state:
    st.session_state['n_periods_past'] = 1050
if not 'n_periods_forecast' in st.session_state:
    st.session_state['n_periods_forecast'] = 90

@st.cache(allow_output_mutation=True)
def get_data(n_periods_past, n_periods_forecast):
    actuals = session.table("CORN_PRICE_DAILY").to_pandas()
    forecast = (session.table_function('forecast', lit(n_periods_forecast))
                    .filter(col('DATE') > F.dateadd('day', -lit(n_periods_past), F.current_date()) )
                    .to_pandas()
                )
    
    actuals = session.table('corn_price_daily').select(col('DATE'),col('VALUE')).to_pandas() 
    actuals.columns = ['DATE', 'ACTUAL']

    forecast = forecast.set_index('DATE').join(actuals.set_index('DATE'), how='left').reset_index()
    forecast = forecast.sort_values('DATE')

    # recommendation rules for forecast
    forecast['RECOMMENDATION'] = 'Hold'
    forecast.loc[forecast['ACTUAL'] > forecast['YHAT_UPPER'], 'RECOMMENDATION'] = 'Sell'
    forecast.loc[forecast['ACTUAL'] < forecast['YHAT_LOWER'], 'RECOMMENDATION'] = 'Buy'

    forecast.loc[(pd.isna(forecast['ACTUAL']) & ((forecast['YHAT'] / forecast['YHAT'].shift(45)) > 1.01)), 'RECOMMENDATION'] = 'Sell'
    forecast.loc[(pd.isna(forecast['ACTUAL']) & ((forecast['YHAT'] / forecast['YHAT'].shift(44)) < 0.99)), 'RECOMMENDATION'] = 'Buy'

    return forecast

df = get_data(st.session_state['n_periods_past'], st.session_state['n_periods_forecast'])



st.header("Corn Price History and Forecast")


current_date_data = df.loc[df['DATE'] == df.loc[~pd.isnull(df['ACTUAL']), 'DATE'].max()] .reset_index()

def retrain_model(periods=None):
    session.call('train_prophet', periods)


with st.sidebar:
    with st.form(key='form'):
        
        
        st.markdown(
        f"""
            ***Current Price:*** {current_date_data['ACTUAL'][0] :.2f}  
            ***Upper Prediction Limit:*** {current_date_data['YHAT_UPPER'][0] :.2f}  
            ***Lower Prediction Limit:*** {current_date_data['YHAT_LOWER'][0] :.2f}  
            ***Current Recommendation:*** {current_date_data['RECOMMENDATION'][0]}

            Prescriptive rules: If current price is greater than the upper prediction limit, sell is recommended. If current price is less than the upper prediction limit, buy is recommended. 
        """
        )
        n_periods_past = st.slider(label="Number of Past Days", min_value=1, max_value=365*30, key='n_periods_past')
        st.slider(label="Number of Forecast Days", min_value=1, max_value=365, key='n_periods_forecast')
        submit_button = st.form_submit_button("Retrain Model", on_click=retrain_model(n_periods_past)   )
    


def fillcol(label):
    st.text(label)
    if label == 'Buy':
        return 'rgba(0,250,0,0.4)'
    elif label == 'Sell':
        return 'rgba(250,0,0,0.4)'
    else:
        return 'rgba(50, 50, 50, 0.4)'


fig = go.Figure([
    go.Scatter(
        name='Predicted Price',
        x=df['DATE'],
        y=df['YHAT'],
        mode='lines',
        line=dict(color='rgb(1, 1, 180)', dash='dot'),
    ),
    go.Scatter(
        name='Actual Price',
        x=df['DATE'],
        y=df['ACTUAL'],
        mode='lines',
        line=dict(color='rgb(31, 119, 180)'),
    ),
    go.Scatter(
        name='Pred Upper',
        x=df['DATE'],
        y=df['YHAT_UPPER'],
        mode='lines',
        marker=dict(color='#444'),
        line=dict(width=0),
        showlegend=False
    ),
    go.Scatter(
        name='Pred Lower',
        x=df['DATE'],
        y=df['YHAT_LOWER'],
        marker=dict(color='#444'),
        line=dict(width=0),
        mode='lines',
        fillcolor='rgba(68, 68, 68, 0.3)',
        fill='tonexty',
        showlegend=False
    ),
])

fig.update_layout(
    xaxis_title='Date',
    yaxis_title='Value',
    title='Corn Prices by Date',
    hovermode='x'
)

fig.update_yaxes(rangemode='tozero')

color_dict= {
                'Buy':'green',
                'Sell':'red',
                'Hold':'grey',}

changes_df = df[df['RECOMMENDATION'] != df['RECOMMENDATION'].shift(1)]
changes = [(c[0], c[1]) for c in changes_df[['DATE','RECOMMENDATION']].values]


for i, val in enumerate(changes):
    if (i+1) == len(changes):
            changes_last_date = changes[-1][0]
            changes_last_state = changes[-1][1]
            last_date= df['DATE'].iloc[-1]
            fig.add_vrect(
                          x0=changes_last_date, x1=last_date,
                          fillcolor=color_dict[changes_last_state], opacity=0.2,
                          layer="below", line_width=0)

    else:
        fig.add_vrect(
                       x0=changes[i][0], x1=changes[i+1][0],
                        fillcolor=color_dict[changes[i][1]], opacity=0.2,
                        layer="below", line_width=0)

fig.update_layout(
    xaxis=dict(
        rangeselector=dict(
            buttons=list([
                dict(count=1,
                     label="1m",
                     step="month",
                     stepmode="backward"),
                dict(count=6,
                     label="6m",
                     step="month",
                     stepmode="backward"),
                dict(count=1,
                     label="YTD",
                     step="year",
                     stepmode="todate"),
                dict(count=1,
                     label="1y",
                     step="year",
                     stepmode="backward"),
                dict(step="all")
            ])
        ),
        rangeslider=dict(
            visible=True
        ),
        type="date"
    )
)

fig.update_layout(legend=dict(
    orientation="h",
    yanchor="bottom",
    y=1.02,
    xanchor="right",
    x=1
))

st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

#st.dataframe(df.loc[df['DATE'] <= datetime.datetime.now().date()].sort_values('DATE', ascending=False) )
st.dataframe(df.sort_values('DATE', ascending=False) )