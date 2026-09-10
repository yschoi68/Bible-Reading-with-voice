import io
import re
import asyncio
import html
from flask import Flask, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import edge_tts

app = Flask(__name__)

TEXT_CACHE = {}

def convert_bible_for_tts(text):
    if not text:
        return text

    def num_to_kor(num_str):
        units = ['', '십', '백', '천']
        digits = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구']
        try:
            n = int(num_str)
        except ValueError:
            return num_str
        if n == 0:
            return '영'
        s_num = str(n)
        length = len(s_num)
        result = ''
        for i, char in enumerate(s_num):
            d = int(char)
            unit_idx = length - i - 1
            if d != 0:
                if d == 1 and unit_idx > 0:
                    result += units[unit_idx]
                else:
                    result += digits[d] + units[unit_idx]
        return result

    def replace_match(match):
        book = match.group(1) or ''
        ch = match.group(2)
        v = match.group(3)
        book_name = book.strip()
        unit = '편' if ('시편' in book_name or book_name == '시') else '장'
        ch_kor = num_to_kor(ch)
        v_kor = re.sub(r'\d+', lambda m: num_to_kor(m.group(0)), v)
        return f"{book_name} {ch_kor}{unit} {v_kor}절"

    return re.sub(r'([가-힣]+)?\s*(\d+)\s*:\s*([\d\s,-]+)', replace_match, text)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/daily-text')
def get_daily_text():
    date_param = request.args.get('date', '')
    if date_param:
        try:
            target_date = datetime.strptime(date_param, '%Y-%m-%d')
        except ValueError:
            target_date = datetime.now()
    else:
        target_date = datetime.now()

    year = target_date.strftime('%Y')
    month = str(target_date.month)
    day = str(target_date.day)

    headers = {'User-Agent': 'Mozilla/5.0'}
    json_url = f"https://wol.jw.org/wol/dt/r8/lp-ko/{year}/{month}/{day}"

    try:
        res = requests.get(json_url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            if 'items' in data and len(data['items']) > 0:
                item = data['items'][0]
                content_html = item.get('content', '')
                soup = BeautifulSoup(content_html, 'html.parser')

                date_text = item.get('title', f"{year}년 {month}월 {day}일")
                
                scrp_elem = soup.select_one('.themeScrp') or soup.select_one('p.pGroup em') or soup.select_one('header h2')
                scripture_text = scrp_elem.text.strip() if scrp_elem else ""

                body_paragraphs = soup.select('.sb') or soup.select('p')
                content_list = []
                for p in body_paragraphs:
                    p_text = p.text.strip()
                    if p_text and p_text != scripture_text and not p_text.startswith(date_text):
                        content_list.append(p_text)
                
                content_text = "\n\n".join(content_list)

                prev_date = (target_date - timedelta(days=1)).strftime('%Y-%m-%d')
                next_date = (target_date + timedelta(days=1)).strftime('%Y-%m-%d')

                full_text = f"{scripture_text}. {content_text}"
                cache_id = f"{year}{month}{day}"
                TEXT_CACHE[cache_id] = full_text

                return jsonify({
                    'success': True,
                    'date': date_text,
                    'scripture': scripture_text,
                    'content': content_text,
                    'prev_date': prev_date,
                    'next_date': next_date,
                    'cache_id': cache_id
                })

        return jsonify({'success': False, 'error': '데이터를 가져오지 못했습니다.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


async def generate_edge_tts_stream(text, voice):
    # XML 특수문자 이스케이프 처리 (&, <, > 방지)
    safe_text = html.escape(text)

    # 마침표 뒤 0.4초, 쉼표 뒤 0.2초 멈춤 지정 / 속도 -5% 감속
    safe_text = safe_text.replace('.', '. <break time="400ms"/>')
    safe_text = safe_text.replace(',', ', <break time="200ms"/>')
    safe_text = safe_text.replace('\n', '<break time="500ms"/>')

    ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ko-KR'>
    <voice name='{voice}'>
        <prosody rate='-5%'>
            {safe_text}
        </prosody>
    </voice>
</speak>"""

    communicator = edge_tts.Communicate(ssml, voice, is_ssml=True)
    async for chunk in communicator.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]


@app.route('/api/tts')
def generate_tts():
    cache_id = request.args.get('cache_id', '')
    gender = request.args.get('gender', 'female')

    text = TEXT_CACHE.get(cache_id, '성경 텍스트를 불러올 수 없습니다.')
    formatted_text = convert_bible_for_tts(text)

    # 남성: 인준 / 여성: 선희
    voice = "ko-KR-InJoonNeural" if gender == "male" else "ko-KR-SunHiNeural"

    def stream_audio():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            gen = generate_edge_tts_stream(formatted_text, voice)
            while True:
                try:
                    chunk = loop.run_until_complete(gen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(stream_audio(), mimetype="audio/mpeg")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
