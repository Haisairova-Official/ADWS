import sys,unittest,math,threading,tempfile,os
from pathlib import Path
from datetime import date,datetime
from unittest.mock import patch
import gi
gi.require_version('Gtk','3.0')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from adws_location import coordinates,ip_location,city_location
from adws_ocean import sample_runs,monotone_segments,tide_at
from urllib.parse import urlparse,parse_qs
from adws_tides import parse_marine,marine,nearby_points,distance_km,MarineUnavailable
from adws_weather import astronomy
from adws_agenda_preview import upcoming


def marine_fixture(now=100000):
    return {'latitude':36.06,'longitude':120.4,'timezone':'Asia/Shanghai','utc_offset_seconds':28800,
            'hourly':{'time':[now+i*3600 for i in range(30)],'sea_level_height_msl':[math.sin(i*math.pi/6) for i in range(30)]}}


class EnvironmentCardsTests(unittest.TestCase):
    def test_ip_is_never_contacted_without_explicit_consent(self):
        with patch('adws_location.json_request') as request:
            for consent in (False,None,1,'true'):
                with self.assertRaises(PermissionError):ip_location(consent=consent)
            request.assert_not_called()
        with patch('adws_location.json_request',return_value={'latitude':36.06,'longitude':120.4,'city':'Qingdao','ip':'PRIVATE'}):
            result=ip_location(consent=True)
            self.assertEqual(result['source'],'ip');self.assertNotIn('ip',result)

    def test_manual_city_never_uses_geolocation(self):
        with patch('adws_location.json_request',return_value={'results':[{'latitude':36.06,'longitude':120.4,'name':'青岛','country':'中国'}]}) as request,patch('adws_location.system_location') as system,patch('adws_location.ip_location') as ip:
            location=city_location('青岛')
            self.assertEqual(location['source'],'city')
            self.assertEqual(parse_qs(urlparse(request.call_args.args[0]).query)['name'],['青岛'])
            system.assert_not_called();ip.assert_not_called()
        with patch('adws_location.json_request') as request:
            self.assertEqual(city_location('36.06,120.4')['latitude'],36.06)
            request.assert_not_called()
        with patch('adws_location.json_request',return_value={'results':[]}):
            with self.assertRaises(ValueError):city_location('Missing city')

    def test_chinese_city_short_name_fallback(self):
        result={'latitude':36.06,'longitude':120.4,'name':'青岛市'}
        with patch('adws_location.json_request',side_effect=[{}, {'results':[result]}]) as request:
            self.assertEqual(city_location('青岛')['name'],'青岛市')
            self.assertEqual([parse_qs(urlparse(call.args[0]).query)['name'][0] for call in request.call_args_list],['青岛','青岛市'])

    def test_smooth_tide_curve_preserves_samples_and_extrema(self):
        points=[(0,0),(1,3),(2,-2),(4,1),(5,1)]
        segments=monotone_segments(points)
        for i,(a,c1,c2,b) in enumerate(segments):
            self.assertEqual(a,points[i]);self.assertEqual(b,points[i+1])
            for step in range(101):
                t=step/100
                y=(1-t)**3*a[1]+3*(1-t)**2*t*c1[1]+3*(1-t)*t*t*c2[1]+t**3*b[1]
                self.assertGreaterEqual(y,min(a[1],b[1])-1e-10)
                self.assertLessEqual(y,max(a[1],b[1])+1e-10)
        self.assertEqual(segments[0][2][1],3)
        self.assertEqual(segments[1][1][1],3)
        self.assertEqual(sample_runs([(0,1),(3600,2),(7200,None),(10800,1),(18000,2)]),[[(0,1),(3600,2)],[(10800,1)],[(18000,2)]])

    def test_current_tide_marker_uses_chart_curve_and_respects_gaps(self):
        samples=[(0,0),(3600,2),(7200,1),(10800,None),(14400,3),(21600,4)]
        self.assertEqual(tide_at(samples,3600),2)
        start,c1,c2,end=monotone_segments(samples[:3])[0]
        expected=(start[1]+3*c1[1]+3*c2[1]+end[1])/8
        self.assertAlmostEqual(tide_at(samples,1800),expected)
        for stamp in (-1,9000,10800,14400,18000,21601):self.assertIsNone(tide_at(samples,stamp))
        self.assertEqual(tide_at([(0,1),(3600,1)],1800),1)

    def test_invalid_coordinates_cannot_reach_forecast(self):
        for lat,lon in ((None,1),(float('nan'),1),(91,1),(1,181),(True,1)):
            with self.assertRaises((TypeError,ValueError)):coordinates(lat,lon)

    def test_tide_extrema_and_missing_gaps(self):
        location={'latitude':36.06,'longitude':120.4,'name':'Coast','source':'fixture'}
        data=marine_fixture();result=parse_marine(data,location,now=100000)
        self.assertEqual(result['peaks'][0]['kind'],'预计高点')
        self.assertEqual(result['peaks'][0]['time'],110800)
        self.assertAlmostEqual(result['peaks'][0]['height'],1)
        data['hourly']['sea_level_height_msl'][3]=None
        result=parse_marine(data,location,now=100000)
        self.assertFalse(any(p['time']==110800 for p in result['peaks']))
        self.assertIn((110800,None),result['samples'])

    def test_inland_empty_and_outdated_model_rejected(self):
        location={'latitude':36.06,'longitude':120.4}
        data=marine_fixture();data['latitude']=40
        with self.assertRaises(ValueError):parse_marine(data,location,now=100000)
        data=marine_fixture();data['hourly']['sea_level_height_msl']=[None]*30
        with self.assertRaises(ValueError):parse_marine(data,location,now=100000)
        with self.assertRaises(ValueError):parse_marine(marine_fixture(),location,now=1000000)

    def test_marine_fallback_chooses_closest_valid_grid_from_one_batch(self):
        location={'latitude':36.06,'longitude':120.4,'name':'City'}
        empty=marine_fixture();empty['hourly']['sea_level_height_msl']=[None]*30
        near=marine_fixture();near['longitude']=120.6
        far=marine_fixture();far['longitude']=120.8
        too_far=marine_fixture();too_far['longitude']=123
        with patch('adws_tides.time.time',return_value=100000),patch('adws_tides.json_request',side_effect=[empty,[too_far,far,empty,near]]) as request:
            result=marine(location)
            self.assertEqual(result['longitude'],120.6);self.assertTrue(result['nearby'])
            self.assertEqual(result['location'],location);self.assertLess(result['distance'],50)
            self.assertEqual(request.call_count,2)
            self.assertEqual(len(parse_qs(urlparse(request.call_args.args[0]).query)['latitude'][0].split(',')),24)

    def test_marine_direct_success_and_transport_error_do_not_search(self):
        location={'latitude':36.06,'longitude':120.4}
        with patch('adws_tides.time.time',return_value=100000),patch('adws_tides.json_request',return_value=marine_fixture()) as request:
            self.assertFalse(marine(location).get('nearby'));request.assert_called_once()
        with patch('adws_tides.json_request',side_effect=TimeoutError) as request:
            with self.assertRaises(TimeoutError):marine(location)
            request.assert_called_once()

    def test_no_coast_remains_unavailable_and_search_is_bounded(self):
        empty=marine_fixture();empty['hourly']['sea_level_height_msl']=[None]*30
        with patch('adws_tides.time.time',return_value=100000),patch('adws_tides.json_request',side_effect=[empty,[empty]*24]) as request:
            with self.assertRaises(MarineUnavailable):marine({'latitude':36.06,'longitude':120.4})
            self.assertEqual(request.call_count,2)
        for origin in ((31.22,121.46),(0,179.99),(89.99,0)):
            points=nearby_points(*origin);self.assertEqual(len(points),24)
            for point in points:
                self.assertLessEqual(distance_km(origin,point),45.02)
                coordinates(*point)

    def test_astronomy_handles_midnight_and_polar_missing_values(self):
        sky=astronomy({'date':'2026-10-09','astronomy':[{'sunrise':'06:00 AM','sunset':'06:30 PM','moonrise':'12:00 AM','moon_illumination':0}]})
        self.assertEqual(sky['daylight'],750);self.assertEqual(sky['moonrise'],'00:00');self.assertEqual(sky['illumination'],'0')
        empty=astronomy({'astronomy':[{'sunrise':'No sunrise','sunset':'No sunset'}]})
        self.assertIsNone(empty['daylight']);self.assertEqual(empty['sunrise'],'—')

    def test_upcoming_crosses_year_and_sorts(self):
        def event(day,time=''):return {'date':day,'time':time,'title':'Test'}
        result=upcoming([event('2027-01-03'),event('2026-12-28','18:00'),event('2026-12-28'),event('2026-12-27'),event('2027-01-04')],date(2026,12,28))
        self.assertEqual(len(result),3);self.assertEqual(result[0]['time'],'');self.assertEqual(result[-1]['date'],'2027-01-03')

    def test_location_registration_does_not_overwrite_user_entry(self):
        from adws_location_registration import register_location_app,remove_location_registration,registration_path
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,{'XDG_DATA_HOME':temporary}):
            register_location_app();path=registration_path();self.assertTrue(path.is_file())
            remove_location_registration();self.assertFalse(path.exists())
            path.write_text('User entry')
            with self.assertRaises(ValueError):register_location_app()
            remove_location_registration();self.assertEqual(path.read_text(),'User entry')
