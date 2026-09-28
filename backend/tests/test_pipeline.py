import os, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import patch

os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='recipe_reel_test_')
from app.media import validate_youtube, PipelineError, run, probe, ingest
from app.models import Cut, Draft, Segment
from app.intelligence import captions, plan
from app import store
from app import render as renderer
from app import main as api
from app import gemini
import httpx

class PipelineTests(unittest.TestCase):
    def test_old_env_model_names_are_migrated(self):
        self.assertEqual(gemini.current_model('models/gemini-2.5-flash'),'gemini-3.8-flash')
        self.assertEqual(gemini.current_model('gemini-flash-latest'),'gemini-3.8-flash')
        self.assertEqual(gemini.current_model('gemini-2.5-flash-lite'),'gemini-3.5-flash-lite')

    def test_transient_gemini_overload_uses_fallback(self):
        request=httpx.Request('POST',gemini.BASE+'gemini-3.8-flash:generateContent')
        calls=[]
        def fake_post(url,**kwargs):
            calls.append(url)
            if 'gemini-3.8-flash:' in url:
                return httpx.Response(503,request=request,json={'error':{'message':'high demand'}})
            return httpx.Response(200,request=request,json={'candidates':[{'content':{'parts':[{'text':'ready'}]}}]})
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test','GEMINI_FALLBACK_MODEL':'gemini-3.5-flash-lite'}),patch.object(gemini.httpx,'post',side_effect=fake_post),patch.object(gemini.time,'sleep'):
            self.assertEqual(gemini.text(gemini.generate('gemini-3.8-flash',[{'text':'test'}])),'ready')
        self.assertEqual(len(calls),4)
        self.assertIn('gemini-3.5-flash-lite:',calls[-1])

    def test_invalid_key_is_not_retried(self):
        request=httpx.Request('POST',gemini.BASE+'gemini-3.8-flash:generateContent')
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test'}),patch.object(gemini.httpx,'post',return_value=httpx.Response(400,request=request,json={'error':{'message':'bad key'}})) as post:
            with self.assertRaisesRegex(PipelineError,'400'):
                gemini.generate('gemini-3.8-flash',[{'text':'test'}])
        post.assert_called_once()

    def test_quota_error_is_not_retried_or_sent_to_fallback(self):
        request=httpx.Request('POST',gemini.BASE+'gemini-3.8-flash-tts:generateContent')
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test','GEMINI_TTS_FALLBACK_MODEL':'another-tts'}),patch.object(gemini.httpx,'post',return_value=httpx.Response(429,request=request,json={'error':{'message':'quota exceeded'}})) as post:
            with self.assertRaisesRegex(PipelineError,'No automatic retry'):
                gemini.generate('gemini-3.8-flash-tts',[{'text':'test'}],{'responseModalities':['AUDIO']})
        post.assert_called_once()

    def test_youtube_validation_rejects_redirect_hosts_and_playlists(self):
        self.assertEqual(validate_youtube('https://youtu.be/dQw4w9WgXcQ'),'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        for url in ['https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ','http://youtube.com/watch?v=dQw4w9WgXcQ','https://youtube.com/playlist?list=abc','https://youtube.com/watch?v=invalid']:
            with self.assertRaises(PipelineError): validate_youtube(url)

    def test_subtitle_rate_limit_falls_back_without_losing_video(self):
        job_id=uuid.uuid4().hex; folder=store.ROOT/job_id; folder.mkdir()
        calls=[]
        def fake_run(args,timeout=600):
            calls.append(args)
            if '--dump-single-json' in args:
                return '{"duration": 60, "title": "Test", "language": "hi"}'
            if '--skip-download' in args:
                raise PipelineError('HTTP Error 429: Too Many Requests')
            (folder/'source.mp4').write_bytes(b'video')
            return ''
        with patch('app.media.run',side_effect=fake_run):
            source,meta=ingest(job_id,'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.assertTrue(source.exists())
        self.assertIn('rate limited',meta['caption_warning'])
        self.assertNotIn('--write-auto-subs',calls[1])
        self.assertEqual(calls[2][calls[2].index('--sub-langs')+1],'hi')

    def test_caption_timestamps_and_dedup(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'source.bn.vtt').write_text('WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nপেঁয়াজ কাটুন\n\n00:00:02.000 --> 00:00:04.000\nপেঁয়াজ কাটুন\n\n00:00:05.000 --> 00:00:06.000\nতেল দিন\n\n00:00:07.000 --> 00:00:08.000\nলবণ দিন\n\n00:00:09.000 --> 00:00:10.000\nভাজুন\n\n00:00:11.000 --> 00:00:12.000\nপরিবেশন করুন\n',encoding='utf8')
            segments,lang,_=captions(Path(folder),'bn')
            self.assertEqual(lang,'bn');self.assertEqual(len(segments),5)
            self.assertEqual((segments[0].start,segments[0].end),(1,3))

    def test_planner_rejects_unanchored_and_out_of_range_cuts(self):
        transcript=[Segment(start=10,end=20,text='Add salt',uncertain=True)]
        proposed={'dish':'Soup','source_language':'en','warnings':[], 'cuts':[
            {'source_start':10,'source_end':15,'purpose':'Salt','source_evidence':'Add salt','narration_text':'Add salt','uncertain':True},
            {'source_start':80,'source_end':88,'purpose':'Invented','source_evidence':'none','narration_text':'Bake','uncertain':False}]}
        job={'duration':30,'output_language':'en','metadata':{'duration':40,'title':'Soup'}}
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test'}),patch('app.intelligence.ask_json',return_value=proposed):
            result=plan(job,transcript,'en',True)
        self.assertEqual(len(result.cuts),1)
        self.assertTrue(any('coarse' in w for w in result.warnings))

    def test_retry_reuses_downloaded_source(self):
        job_id=store.create('https://www.youtube.com/watch?v=dQw4w9WgXcQ',30,'en')
        source=store.ROOT/job_id/'source.mp4'; source.write_bytes(b'present')
        store.update(job_id,state='failed',metadata={'source_file':'source.mp4','duration':20,'title':'Test'})
        draft=Draft(dish='Test',source_language='en',output_language='en',transcript=[Segment(start=0,end=5,text='cook')],cuts=[Cut(id='a',source_start=0,source_end=3,purpose='Cook',source_evidence='cook',narration_text='Cook')])
        with patch('app.main.ingest') as download,patch('app.main.get_transcript',return_value=(draft.transcript,'en',False)),patch('app.main.plan',return_value=draft):
            api.run_analysis(job_id)
        download.assert_not_called()
        self.assertEqual(store.get(job_id)['state'],'review')

    def test_real_media_render_has_audio_and_subtitles(self):
        job_id=uuid.uuid4().hex; folder=store.ROOT/job_id;folder.mkdir()
        source=folder/'source.mp4'
        run(['ffmpeg','-y','-f','lavfi','-i','color=c=orange:s=320x240:r=30:d=5','-f','lavfi','-i','anullsrc=r=44100:cl=mono', '-shortest','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],90)
        speech=folder/'fake_voice.wav'
        run(['ffmpeg','-y','-f','lavfi','-i','sine=frequency=440:duration=2.5','-c:a','pcm_s16le',str(speech)],90)
        draft=Draft(dish='Test',source_language='en',output_language='kn',transcript=[Segment(start=0,end=5,text='cook')],cuts=[Cut(id='a',source_start=0,source_end=2,purpose='Cook',source_evidence='cook',narration_text='ಬೇಯಿಸಿ'),Cut(id='b',source_start=2,source_end=4,purpose='Serve',source_evidence='serve',narration_text='ಬಡಿಸಿ')])
        job={'id':job_id,'duration':30,'output_language':'kn','metadata':{'source_file':'source.mp4'}}
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test'}),patch.object(renderer,'generate',return_value=[{'inlineData':{'data':__import__('base64').b64encode(speech.read_bytes()).decode()}}]):
            output,seconds=renderer.render(job,draft,speed=2)
        self.assertTrue(output.exists());self.assertGreater(seconds,5.0)
        streams=probe(output)['streams']
        self.assertEqual({s['codec_type'] for s in streams},{'video','audio','subtitle'})
        video=next(s for s in streams if s['codec_type']=='video')
        self.assertEqual((video['width'],video['height']),(720,1280))
        self.assertIn('ಬೇಯಿಸಿ',(folder/'captions.vtt').read_text(encoding='utf8'))

if __name__=='__main__': unittest.main()
