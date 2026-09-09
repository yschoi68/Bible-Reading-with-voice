import io
import asyncio
from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import edge_tts

app = Flask(__name__)

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
    month = target_date.strftime('%m')
    day = target_date.strftime('%d')
    url = f"https://wol.jw.org/ko/wol/h/r8/lp-ko/{year}/{month}/{day}"

    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        response = requests.get(url, headers=headers)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            items = soup.select('.tabContent .items .item')
            
            target_item = None
            for item in items:
                header = item.select_one('header h2')
                if header:
                    target_item = item
                    break

            if target_item:
                date_text = target_item.select_one('header h2').text.strip()
                scripture_text = target_item.select_one('.pGroup .themeScrp').text.strip()
                
                body_paragraphs = target_item.select('.pGroup .sb')
                content_text = "\n\n".join([p.text.strip() for p in body_paragraphs])

                prev_date = (target_date - timedelta(days=1)).strftime('%Y-%m-%d')
                next_date = (target_date + timedelta(days=1)).strftime('%Y-%m-%d')

                return jsonify({
                    'success': True,
                    'date': date_text,
                    'scripture': scripture_text,
                    'content': content_text,
                    'prev_date': prev_date,
                    'next_date': next_date
                })

        return jsonify({'success': False, 'error': '데이터를 찾을 수 없습니다.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/tts')
def generate_tts():
    text = request.args.get('text', '')
    gender = request.args.get('gender', 'male')

    if not text:
        return "No text provided", 400

    # 발음 보정
    formatted_text = convert_bible_for_tts(text)

    # Edge AI 고품질 보이스 선택
    # 남성: InJoon, 여성: SunHi
    voice = 'ko-KR-InJoonNeural' if gender == 'male' else 'ko-KR-SunHiNeural'

    async def _generate():
        communicate = edge_tts.Communicate(formatted_text, voice, rate="-5%", pitch="-2Hz" if gender == 'male' else "+0Hz")
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    try:
        # 비동기 오디오 생성
        audio_bytes = asyncio.run(_generate())
        return send_file(
            io.BytesIO(audio_bytes),
            mimetype="audio/mpeg",
            as_attachment=False,
            download_name="speech.mp3"
        )
    except Exception as e:
        return str(e), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
