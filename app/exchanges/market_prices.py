"""Worker-refreshed prices; HTTP handlers only read the persistent account snapshot."""
from datetime import datetime, timezone
from decimal import Decimal
import logging
import requests
from app.core.logging_utils import log_transition, clear_transition

LOG=logging.getLogger('bitcoin-dca.prices')


def collect_prices(api, settings, price):
    quote=settings['quote']
    prices={quote:format(price,'f')}
    other='USD' if quote=='EUR' else 'EUR'
    try:
        if settings['exchange']=='KRAKEN':
            alternate=Decimal(str(api.price('BTC-'+other)))
        else:
            # Bitvavo trades BTC/EUR; use Kraken solely for the display conversion.
            response=api.session.get('https://api.kraken.com/0/public/Ticker',
                                     params={'pair':'XBTUSD'},timeout=15)
            response.raise_for_status();payload=response.json()
            if payload.get('error'): raise ValueError('Kraken conversion ticker unavailable')
            alternate=Decimal(str(next(iter(payload['result'].values()))['c'][0]))
        if not alternate.is_finite() or alternate<=0: raise ValueError('Invalid conversion price')
        prices[other]=format(alternate,'f')
        clear_transition(api,'display-price')
    except (requests.RequestException,ValueError,ArithmeticError,KeyError,StopIteration,TypeError):
        needed=settings.get('display_currency',quote)!=quote
        log_transition(LOG,api,'display-price','missing-'+other,logging.WARNING if needed else logging.DEBUG,
                       'BTC/%s display conversion unavailable; BTC/%s purchase price remains current.',other,quote)
        LOG.debug('Display conversion refresh failed',exc_info=True)
    return prices


def snapshot_market_price(snapshot, exchange, display_currency, quote_currency, currencies=()):
    needed={display_currency,quote_currency,*currencies}
    if not needed <= {'EUR','USD'}: raise ValueError('Display and historical fiat currencies must be EUR or USD')
    if snapshot.get('exchange')!=exchange or snapshot.get('quote')!=quote_currency:
        raise RuntimeError('Waiting for account check')
    prices={c:Decimal(str(v)) for c,v in snapshot.get('marketPrices',{}).items()}
    if not needed <= prices.keys(): raise RuntimeError('Waiting for account price check')
    if any(not prices[c].is_finite() or prices[c]<=0 for c in needed): raise RuntimeError('Account price unavailable')
    updated=datetime.fromisoformat(snapshot['updatedAt'].replace('Z','+00:00')).timestamp()
    target=prices[display_currency]
    return {'currency':display_currency,'quoteCurrency':quote_currency,'price':str(target),
            'conversionRate':str(target/prices[quote_currency]),
            'conversionRates':{c:str(target/v) for c,v in prices.items()},
            'source':'Last account check','updatedAt':updated,
            'stale':datetime.now(timezone.utc).timestamp()-updated>600}
