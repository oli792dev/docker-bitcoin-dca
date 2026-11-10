"""Real HTTPS application with isolated storage and an offline exchange."""

import json
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app.core import configuration
from app.core.lifecycle import shutdown_signals
from app.data import activity, storage
from app.exchanges.exchange_errors import DefinitiveRejection
from app.exchanges.kraken import Kraken
from app.trading import bot, runtime, worker
from app.webpage import tls, web_ui


class OfflineExchange:
    normalize_bot_buy = Kraken.normalize_bot_buy

    def __init__(self):
        self.attempts = 0
        self.fiat = Decimal('100')
        self.btc = Decimal('0')
        self.order = None

    def balance(self, currency):
        return self.btc if currency == 'BTC' else self.fiat

    def price(self, symbol):
        return Decimal('80000') if symbol == 'BTC-EUR' else Decimal('95000')

    def market(self, symbol, refresh=False):
        return dict(status='trading', minOrderInBaseAsset='.0001', minOrderInQuoteAsset='5',
                    quantityDecimals=8, notionalDecimals=2)

    def estimate_taker_fee(self, symbol, amount):
        return amount * Decimal('.0025')

    def fiat_deposits(self, *args):
        return []

    def btc_withdrawals(self, *args):
        return []

    def open_orders(self):
        return []

    def buy_btc(self, quote, amount, client_id):
        self.attempts += 1
        if self.attempts == 1:
            raise DefinitiveRejection('PRIVATE EXCHANGE DETAIL', code='EGeneral:Permission denied',
                                      category='permission_denied')
        cost = amount * self.price('BTC-EUR')
        fee = cost * Decimal('.0025')
        self.fiat -= cost + fee
        self.btc += amount
        self.order = dict(status='closed', vol_exec=str(amount), cost=str(cost), fee=str(fee),
                          closetm=datetime.now(UTC).timestamp())
        return {'orderId':'offline-order'}

    def get_order(self, *args):
        return self.order


def main():
    with tempfile.TemporaryDirectory(prefix='dca-live-test-') as temporary, ExitStack() as patches:
        root = Path(temporary)
        for owner, name, value in (
            (storage, 'DATA_DIR', root), (bot, 'STATE_PATH', root/'state.json'),
            (activity, 'ACTIVITY_PATH', root/'activity.sqlite3'),
            (activity, 'SNAPSHOT_PATH', root/'dashboard.json'),
            (worker, 'HEALTH_PATH', root/'worker-health.json'), (tls, 'DATA_DIR', root),
        ):
            patches.enter_context(patch.object(owner, name, value))
        patches.enter_context(patch.object(runtime, 'create_exchange', return_value=OfflineExchange()))
        patches.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('External requests are forbidden in the HTTPS fixture')))
        storage.prepare_storage(root)
        app = runtime.Runtime(configuration.ConfigStore(root/'config.json'), root/'state.json')
        real_server = tls.HTTPSWebServer

        def server(address, handler):
            instance = real_server(('127.0.0.1', 0), handler)
            print(json.dumps({'url':f'https://127.0.0.1:{instance.server_port}'}), flush=True)
            return instance

        patches.enter_context(patch.object(tls, 'HTTPSWebServer', side_effect=server))
        with shutdown_signals(app.worker) as stop:
            app.worker.start()
            try:
                web_ui.serve(app.settings, 0, app.worker.submit, worker=app.worker, runtime=app, stop=stop)
            finally:
                app.shutdown()


if __name__ == '__main__':
    main()
