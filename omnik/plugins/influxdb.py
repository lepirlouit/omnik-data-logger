import json
from datetime import datetime, timedelta
import pytz

import urllib.parse
import requests

from omnik.plugins import Plugin


class influxdb(Plugin):

    def __init__(self):
        super().__init__()
        self.name = 'influxdb'
        self.description = 'Write output to InfluxDB'
        tz = self.config.get('default', 'timezone',
                             fallback='Europe/Amsterdam')
        self.timezone = pytz.timezone(tz)

    def get_weather(self):
        try:
            if 'weather' not in self.cache:
                self.logger.debug('[cache miss] Fetching weather data')
                url = "https://{endpoint}/data/2.5/weather?lon={lon}&lat={lat}&units={units}&APPID={api_key}".format(
                    endpoint=self.config.get('openweathermap', 'endpoint'),
                    lat=self.config.get('openweathermap', 'lat'),
                    lon=self.config.get('openweathermap', 'lon'),
                    units=self.config.get(
                        'openweathermap', 'units', fallback='metric'),
                    api_key=self.config.get('openweathermap', 'api_key'),
                )

                res = requests.get(url)

                res.raise_for_status()

                self.cache['weather'] = res.json()

            return self.cache['weather']

        except requests.exceptions.HTTPError as e:
            self.logger.error('Unable to get data. [{0}]: {1}'.format(
                type(e).__name__, str(e)))
            raise e

    def process(self, **args):
        """
        Send data to influxdb
        """
        try:
            msg = args['msg']

            self.logger.debug(json.dumps(msg, indent=2))

            if not self.config.has_option('influxdb', 'database') or not self.config.has_option('influxdb', 'table'):
                self.logger.error(
                    f'[{__name__}] No database and/or table found in configuration')
                return

            host = self.config.get('influxdb', 'host', fallback='localhost')
            port = self.config.get('influxdb', 'port', fallback='8086')
            database = self.config.get('influxdb', 'database')
            table = self.config.get('influxdb', 'table')

            headers = {
                "Content-type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }

            values = msg.copy()
            if self.config.getboolean('influxdb', 'use_temperature', fallback=False):
                weather = self.get_weather()
                values['temp'] = str(weather['main']['temp'])

            last_update_time = values.pop('last_update_time')
            timezone = values.pop('timezone')
            values.pop('currency')
            nanoepoch = int(
                (
                    datetime.strptime(last_update_time, '%Y-%m-%dT%H:%M:%SZ') +
                    timedelta(hours=int(timezone[1:3]), minutes=int(timezone[4:5])) *
                    (-1 if timezone[0] == '-' else 1)
                ).timestamp() * 1000000000
            )
            encoded = f'{table},plant=p1 {",".join("{}={}".format(key, value) for key, value in values.items())} {nanoepoch}'

            self.logger.debug(json.dumps(values, indent=2))
# curl -i -XPOST 'http://localhost:8086/write?db=mydb' --data-binary 'cpu_load_short,host=server01,region=us-west value=0.64 1434055562000000000'
            url = f'http://{host}:{port}/write?db={database}'

            r = requests.post(url, data=encoded, headers=headers)

            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.status_code == '400':
                # Client Error: Bad Request
                self.logger.warn(f"Got error from influxdb: {str(e)} (ignoring: if this happens a lot ... fix it)")
            elif e.status_code == '504':
                # Gateway Time-out
                pass

        except Exception as e:
            self.logger.error(e, exc_info=True)
            raise e


