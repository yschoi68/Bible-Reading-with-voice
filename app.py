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
    """
    성구 구절(예: '요한 3:16', '시편 23:1-4')을 
    TTS가 정확하게 읽을 수 있도록 한글(예: '요한 삼장 십육절')로 변환하는 함수
    """
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
    month = str(target_date.month)  # JSON API용 (앞자리 0 제거)
    day = str(target_date.day)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

    # 1차 시도: JW.ORG 공식 Daily Text API (JSON)
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
                
                # 성구 구절 파싱
                scrp_elem = soup.select_one('.themeScrp') or soup.select_one('p.pGroup em') or soup.select_one('header h2')
                scripture_text = scrp_elem.text.strip() if scrp_elem else ""

                # 본문 내용 파싱
                body_paragraphs = soup.select('.sb') or soup.select('p')
                content_list = []
                for p in body_paragraphs:
                    p_text = p.text.strip()
                    if p_text and p_text != scripture_text and not p_text.startswith(date_text):
                        content_list.append(p_text)
                
                content_text = "\n\n".join(content_list)

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

        # 2차 시도 (Fallback): HTML 직접 크롤링
        html_url = f"https://wol.jw.org/ko/wol/h/r8/lp-ko/{year}/{target_date.strftime('%m')}/{target_date.strftime('%d')}"
        response = requests.get(html_url, headers=headers, timeout=8)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            items = soup.select('.tabContent .items .item') or soup.select('article')
            
            target_item = items[0] if items else None
            if target_item:
                date_elem = target_item.select_one('header h2') or target_item.select_one('h2')
                date_text = date_elem.text.strip() if date_elem else ""

                scrp_elem = target_item.select_one('.themeScrp') or target_item.select_one('p')
                scripture_text = scrp_elem.text.strip() if scrp_elem else ""
                
                body_paragraphs = target_item.select('.pGroup .sb') or target_item.select('.sb')
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

    # 성구 발음 보정 적용
    formatted_text = convert_bible_for_tts(text)

    # Microsoft Edge 고품질 AI 음성 모델 지정
    # 남성: ko-KR-InJoonNeural (인준)
    # 여성: ko-KR-SunHiNeural (선히)
    voice = 'ko-KR-InJoonNeural' if gender == 'male' else 'ko-KR-SunHiNeural'

    async def _generate():
        communicate = edge_tts.Communicate(
            formatted_text, 
            voice, 
            rate="-4%", 
            pitch="-2Hz" if gender == 'male' else "+0Hz"
        )
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    try:
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
