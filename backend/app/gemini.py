import json
import os
import random
import time
import httpx
from .media import PipelineError

BASE = 'https://generativelanguage.googleapis.com/v1beta/models/'
LEGACY_MODELS = {
    'gemini-flash-latest': 'gemini-3.8-flash',
    'gemini-2.5-flash': 'gemini-3.8-flash',
    'gemini-2.5-flash-lite': 'gemini-3.5-flash-lite',
}

def current_model(model):
    return LEGACY_MODELS.get(model.strip().removeprefix('models/'), model.strip().removeprefix('models/'))

def generate(model, parts, config=None):
    key = os.getenv('GEMINI_API_KEY')
    if not key:
        raise PipelineError('Set GEMINI_API_KEY in backend/.env and restart the backend')
    payload = {'contents': [{'parts': parts}]}
    if config:
        payload['generationConfig'] = config
    model = current_model(model)
    is_speech = 'AUDIO' in (config or {}).get('responseModalities', [])
    fallback = (os.getenv('GEMINI_TTS_FALLBACK_MODEL', 'gemini-3.8-flash-lite-tts') if is_speech
                else os.getenv('GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')).strip()
    fallback = current_model(fallback) if fallback else ''
    models = [model]
    if fallback and fallback != model:
        models.append(fallback)
    for index, candidate in enumerate(models):
        for attempt in range(3):
            try:
                response = httpx.post(f'{BASE}{candidate}:generateContent', headers={'x-goog-api-key': key}, json=payload, timeout=120)
                response.raise_for_status()
                return response.json()['candidates'][0]['content']['parts']
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                # A quota/rate-limit response must not trigger retries or a fallback
                # request. Those would consume more quota without solving the issue.
                if status == 429:
                    raise PipelineError(
                        f'Gemini quota or rate limit reached for {candidate}. '
                        'No automatic retry was sent. Wait for your Gemini quota to reset, '
                        'check availability in Google AI Studio, then try Generate once. '
                        'This app cannot increase provider quota or enable billing for you.'
                    ) from exc
                if status in (500, 502, 503, 504) and attempt < 2:
                    time.sleep(min(2 ** attempt + random.random(), 4))
                    continue
                if status in (500, 502, 503, 504) and index + 1 < len(models):
                    break
                try:
                    detail = exc.response.json().get('error', {}).get('message', '')
                except ValueError:
                    detail = ''
                hint = ' Try again later or select another Gemini model.' if status == 503 else ''
                raise PipelineError(f'Gemini API error ({status}) on {candidate}: {detail[:300]}{hint}') from exc
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                raise PipelineError('Gemini request failed or returned no usable response; retry shortly') from exc

def text(parts):
    return ''.join(part.get('text', '') for part in parts).strip()
