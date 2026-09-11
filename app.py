from flask import Flask, render_template, jsonify, request
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

app = Flask(__name__)

# 한국어 요일 리스트
WEEKDAYS = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']

def fetch_jw_daily_text(target_date=None):
    """지정한 날짜(YYYY-MM-DD)의 일용할 성구를 WOL 사이트에서 가져오는 함수"""
    if target_date:
        try:
            date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            date_obj = datetime.now()
    else:
        date_obj = datetime.now()

    url = f"https://wol.jw.org/ko/wol/h/r8/lp-ko/{date_obj.year}/{date_obj.month}/{date_obj.day}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # 날짜 포맷팅: YYYY년 MM월 DD일 (요일)
        weekday_name = WEEKDAYS[date_obj.weekday()]
        date_text = f"{date_obj.year}년 {date_obj.month}월 {date_obj.day}일 ({weekday_name})"

        theme_elem = soup.find("p", class_="themeScrp")
        theme_text = theme_elem.get_text(strip=True) if theme_elem else "성구 구절을 찾지 못했습니다."

        sb_elem = soup.find("div", class_="sb") or soup.find("p", class_="sb")
        body_text = sb_elem.get_text(strip=True) if sb_elem else "해설 내용을 찾지 못했습니다."

        prev_date = (date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
        current_date_str = date_obj.strftime("%Y-%m-%d")

        return {
            "success": True,
            "current_date": current_date_str,
            "prev_date": prev_date,
            "next_date": next_date,
            "date": date_text,
            "scripture": theme_text,
            "content": body_text
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"데이터 로딩 실패: {str(e)}"
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/daily-text')
def get_daily_text_api():
    date_param = request.args.get('date', None)
    data = fetch_jw_daily_text(date_param)
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
