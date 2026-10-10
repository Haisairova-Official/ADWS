import sys
import unittest
import locale
from datetime import date, datetime
from pathlib import Path
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_calendar import month_cells
from adws_weather import parse_weather, number, icon, clock_time


def fixture():
    sample={'tempC':'21','FeelsLikeC':'20','humidity':'65','windspeedKmph':'12','chanceofrain':'40','uvIndex':'3','visibility':'10','pressure':'1014','precipMM':'0.1','weatherDesc':[{'value':'Partly cloudy'}],'lang_zh':[{'value':'局部多云'}]}
    return {'current_condition':[dict(sample,temp_C='22',localObsDateTime='2026-10-09 10:00 AM')],
        'weather':[{'date':f'2026-10-{day:02d}','mintempC':'14','maxtempC':'24','astronomy':[{'sunrise':'06:00 AM','sunset':'05:30 PM','moonrise':'09:00 PM','moonset':'10:00 AM','moon_phase':'Waning Crescent','moon_illumination':'12'}],'hourly':[dict(sample,time=str(h*100)) for h in range(0,24,3)]} for day in (9,10,11)]}


class CalendarWeatherTests(unittest.TestCase):
    def test_month_grid_leap_year_and_year_boundary(self):
        cells=month_cells(2024,2)
        self.assertEqual(len(cells),42);self.assertEqual(cells[0].weekday(),0)
        self.assertIn(date(2024,2,29),cells);self.assertEqual(cells[-1],date(2024,3,10))
        self.assertEqual(month_cells(2026,1)[0],date(2025,12,29))
        self.assertEqual(month_cells(1,1)[0],date.min)
        self.assertIn(None,month_cells(9999,12))

    def test_forecast_uses_destination_local_time_and_limits(self):
        data=parse_weather(fixture(),'测试城市',now=datetime(2026,10,9,20))
        self.assertEqual(len(data['days']),3);self.assertEqual(len(data['hours']),6)
        self.assertEqual(data['hours'][0]['time'],'2026-10-09T12:00:00')
        self.assertEqual(data['current']['temperature'],'22')
        self.assertEqual(data['current']['icon'],'weather-few-clouds-symbolic')

    def test_missing_optional_data_never_invents_measurements(self):
        data=parse_weather({'current_condition':[{}]},'City',now=datetime(2026,10,9))
        self.assertEqual(data['current']['humidity'],'—');self.assertEqual(data['days'],[])
        self.assertEqual(number(float('nan')),'—');self.assertEqual(number('bad'),'—')
        self.assertEqual(icon({'weatherDesc':[{'value':'Heavy snow'}]}),'weather-snow-symbolic')

    def test_english_provider_times_in_chinese_desktop_locale(self):
        previous=locale.setlocale(locale.LC_TIME)
        try:
            try:locale.setlocale(locale.LC_TIME,'zh_CN.UTF-8')
            except locale.Error:self.skipTest('Chinese locale unavailable')
            self.assertEqual(clock_time('12:00 AM'),'00:00')
            self.assertEqual(clock_time('12:30 PM'),'12:30')
            self.assertEqual(clock_time('05:30 PM'),'17:30')
            self.assertEqual(clock_time('25:00'),'—')
            data=parse_weather(fixture(),'City',now=datetime(2026,10,10,20))
            self.assertEqual(data['astronomy']['sunrise'],'06:00')
            self.assertEqual(data['astronomy']['sunset'],'17:30')
            self.assertEqual(data['astronomy']['daylight'],690)
            self.assertEqual(data['local_observed'],'2026-10-09T10:00:00')
        finally:locale.setlocale(locale.LC_TIME,previous)

    def test_extra_conditions_preserve_missing_values(self):
        raw=fixture();raw['current_condition'][0].update(winddir16Point='NE',WindGustKmph='18',cloudcover='75')
        current=parse_weather(raw,'City')['current']
        self.assertEqual((current['direction'],current['gust'],current['cloud']),('NE','18','75'))
        current=parse_weather({'current_condition':[{}]},'City')['current']
        self.assertEqual((current['gust'],current['cloud']),('—','—'))

    def test_invalid_payload_rejected_for_cache_preservation(self):
        with self.assertRaises((KeyError,ValueError,IndexError)):parse_weather({},'City')
        invalid=fixture();invalid['weather'][0]['date']='invalid'
        with self.assertRaises(ValueError):parse_weather(invalid,'City')
