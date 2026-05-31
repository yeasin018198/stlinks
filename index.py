import os
import random
import string
import requests
import json
from flask import Flask, render_template_string, request, redirect, url_for, jsonify, session
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from bson.objectid import ObjectId

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "premium-super-secret-key-2025")

# --- সেশন সেটিংস ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

# --- ডাটাবেস কানেকশন ---
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://user:pass@cluster.mongodb.net/test")
client = MongoClient(MONGO_URI, tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=5000)
db = client['premium_urlbot']

urls_col = db['urls']
settings_col = db['settings']
channels_col = db['channels']
otp_col = db['otps']
ad_links_col = db['ad_links']
stats_col = db['stats']
banners_col = db['banners'] # নতুন ডাটাবেস কালেকশন

# --- টেলিগ্রাম সেটিংস ---
TELEGRAM_BOT_TOKEN = "8552256920:AAF6iyUJjJNsCUBVHm_XrxCxtlbnJtqnF2U"

COLOR_MAP = {
    "red": {"text": "text-red-500", "bg": "bg-red-600", "border": "border-red-500", "hover": "hover:bg-red-700", "light_bg": "bg-red-50"},
    "orange": {"text": "text-orange-500", "bg": "bg-orange-600", "border": "border-orange-500", "hover": "hover:bg-orange-700", "light_bg": "bg-orange-50"},
    "yellow": {"text": "text-yellow-500", "bg": "bg-yellow-500", "border": "border-yellow-500", "hover": "hover:bg-yellow-600", "light_bg": "bg-yellow-50"},
    "green": {"text": "text-green-500", "bg": "bg-green-600", "border": "border-green-500", "hover": "hover:bg-green-700", "light_bg": "bg-green-50"},
    "blue": {"text": "text-blue-500", "bg": "bg-blue-600", "border": "border-blue-500", "hover": "hover:bg-blue-700", "light_bg": "bg-blue-50"},
    "sky": {"text": "text-sky-400", "bg": "bg-sky-500", "border": "border-sky-400", "hover": "hover:bg-sky-600", "light_bg": "bg-sky-50"},
    "purple": {"text": "text-purple-500", "bg": "bg-purple-600", "border": "border-purple-500", "hover": "hover:bg-purple-700", "light_bg": "bg-purple-50"},
    "pink": {"text": "text-pink-500", "bg": "bg-pink-600", "border": "border-pink-500", "hover": "hover:bg-pink-700", "light_bg": "bg-pink-50"},
    "slate": {"text": "text-slate-400", "bg": "bg-slate-700", "border": "border-slate-500", "hover": "hover:bg-slate-800", "light_bg": "bg-slate-50"}
}

def get_settings():
    settings = settings_col.find_one()
    if not settings:
        default_settings = {
            "site_name": "Premium URL Shortener",
            "admin_telegram_id": "", 
            "steps": 2,
            "timer_seconds": 10,
            "admin_password": generate_password_hash("admin123"),
            "api_key": ''.join(random.choices(string.ascii_lowercase + string.digits, k=40)),
            "popunder": "", "banner": "", "social_bar": "", "native": "",
            "direct_click_limit": 1,
            "main_theme": "sky", "step_theme": "blue"
        }
        settings_col.insert_one(default_settings)
        return default_settings
    return settings

def is_logged_in(): return session.get('logged_in')

def track_click(short_code, ad_link=None):
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip: ip = ip.split(',')[0]
    country = "Unknown"
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}", timeout=2).json()
        if res.get('status') == 'success': country = res.get('country', 'Unknown')
    except: pass
    ua = request.user_agent.string.lower()
    device = "Mobile" if any(m in ua for m in ['android', 'iphone', 'ipad', 'mobile']) else "Desktop/Laptop"
    stats_col.insert_one({
        "short_code": short_code, "ad_link": ad_link, "country": country,
        "device": device, "timestamp": datetime.now(), "date": datetime.now().strftime("%Y-%m-%d")
    })

def get_channels_html(theme_color="sky"):
    channels = list(channels_col.find())
    if not channels: return ""
    c = COLOR_MAP.get(theme_color, COLOR_MAP['sky'])
    html = f'<div class="w-full max-w-5xl mx-auto mt-12 mb-8 p-8 rounded-[40px] border-2 border-white/10 glass shadow-2xl text-center"><h3 class="{c["text"]} font-black mb-10 uppercase tracking-widest text-lg">Partner Channels</h3><div class="flex flex-col items-center gap-10">'
    for ch in channels:
        # এখানে img ট্যাগের ক্লাস পরিবর্তন করা হয়েছে যাতে লোগো ফুল সাইজ দেখায়
        html += f'<a href="{ch["link"]}" target="_blank" class="flex flex-col items-center gap-3 group transition hover:scale-105 w-full"><div class="w-full"><p class="text-lg font-black text-gray-100 uppercase italic tracking-wider mb-2">{ch.get("name", "Join Channel")}</p><img src="{ch["logo"]}" class="w-full max-w-[500px] h-auto border-2 border-white/10 rounded-2xl shadow-2xl mx-auto block"></div></a>'
    return html + '</div></div>'

# --- API সিস্টেম ---
@app.route('/api')
def api_system():
    settings = get_settings()
    api_token = (request.args.get('api') or request.args.get('api_key') or request.args.get('key','')).strip()
    long_url = request.args.get('url')
    alias = request.args.get('alias')
    res_format = request.args.get('format', 'json').lower()
    if api_token != settings['api_key'].strip():
        return jsonify({"status": "error", "message": "Invalid API Token"}) if res_format != 'text' else "Error: Invalid Token"
    if not long_url:
        return jsonify({"status": "error", "message": "Missing URL"}) if res_format != 'text' else "Error: Missing URL"
    sc = alias if alias else ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    urls_col.insert_one({"long_url": long_url, "short_code": sc, "clicks": 0, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return request.host_url + sc if res_format == 'text' else jsonify({"status": "success", "shortenedUrl": request.host_url + sc})

# --- হোম পেজ ---
@app.route('/')
def index():
    settings = get_settings()
    c = COLOR_MAP.get(settings.get('main_theme', 'sky'), COLOR_MAP['sky'])
    return render_template_string(f'''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><script src="https://cdn.tailwindcss.com"></script><title>{settings['site_name']}</title><style>body {{ background: #0f172a; color: white; }} .glass {{ background: rgba(255,255,255,0.03); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.1); }}</style></head><body class="min-h-screen flex flex-col items-center justify-center p-6 text-center"><h1 class="text-5xl md:text-9xl font-black mb-6 {c['text']} italic uppercase">{settings['site_name']}</h1><p class="text-gray-200 mb-14 text-xl md:text-4xl font-black uppercase tracking-widest">Premium Shortener System</p><div class="glass p-5 rounded-[50px] w-full max-w-4xl shadow-3xl"><form action="/shorten" method="POST" class="flex flex-col md:flex-row gap-4"><input type="url" name="long_url" placeholder="PASTE LINK HERE..." required class="flex-1 bg-transparent p-6 outline-none text-white text-2xl font-black"><button type="submit" class="{c['bg']} text-white px-14 py-6 rounded-[40px] font-black text-3xl hover:scale-105 transition uppercase">Shorten</button></form></div>{get_channels_html(settings.get('main_theme', 'sky'))}</body></html>''')

@app.route('/shorten', methods=['POST'])
def web_shorten():
    settings = get_settings()
    c = COLOR_MAP.get(settings.get('main_theme', 'sky'), COLOR_MAP['sky'])
    long_url = request.form.get('long_url')
    sc = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    urls_col.insert_one({"long_url": long_url, "short_code": sc, "clicks": 0, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return render_template_string(f'''<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><script src="https://cdn.tailwindcss.com"></script></head><body class="bg-slate-900 flex flex-col items-center justify-center min-h-screen p-4 text-white"><div class="bg-slate-800 p-16 rounded-[60px] shadow-2xl text-center max-w-2xl w-full border border-slate-700"><h2 class="text-5xl font-black mb-10 {c['text']} uppercase italic">Link Created!</h2><input id="shortUrl" value="{request.host_url + sc}" readonly class="w-full bg-slate-900 p-8 rounded-3xl border border-slate-700 {c['text']} font-black text-center mb-10 text-3xl"><button onclick="copyLink()" id="copyBtn" class="w-full {c['bg']} text-white py-8 rounded-[40px] font-black text-4xl uppercase tracking-tighter shadow-2xl">COPY LINK</button><a href="/" class="block mt-10 text-slate-500 font-bold uppercase text-sm">Shorten Another</a></div><script>function copyLink() {{ var copyText = document.getElementById("shortUrl"); copyText.select(); navigator.clipboard.writeText(copyText.value); document.getElementById("copyBtn").innerText = "COPIED!"; }}</script></body></html>''')

# --- এডমিন প্যানেল ---
@app.route('/admin')
def admin_panel():
    if not is_logged_in(): return redirect(url_for('login'))
    settings = get_settings()
    all_urls = list(urls_col.find().sort("_id", -1).limit(50))
    channels = list(channels_col.find())
    ad_links = list(ad_links_col.find())
    banners = list(banners_col.find()) 
    
    today = datetime.now().strftime("%Y-%m-%d")
    total_views = stats_col.count_documents({})
    today_views = stats_col.count_documents({"date": today})
    chart_labels, chart_values = [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        chart_labels.append(d); chart_values.append(stats_col.count_documents({"date": d}))
    countries = list(stats_col.aggregate([{"$group": {"_id": "$country", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 5}]))
    devices = list(stats_col.aggregate([{"$group": {"_id": "$device", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]))
    ad_stats = [{"url": al['url'], "count": stats_col.count_documents({"ad_link": al['url']})} for al in ad_links]

    return render_template_string('''
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Premium Admin</title>
    <script src="https://cdn.tailwindcss.com"></script><script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style> .tab-content { display: none; } .tab-content.active { display: block; } .active-btn { background: #1e293b !important; color: white !important; } 
    ::-webkit-scrollbar { height: 5px; } ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; } </style>
    </head><body class="bg-slate-50 flex flex-col lg:flex-row min-h-screen font-sans">
        <div class="w-full lg:w-72 bg-white border-b lg:border-r p-6 flex lg:flex-col overflow-x-auto lg:overflow-visible sticky top-0 z-50">
            <h2 class="hidden lg:block text-2xl font-black mb-10 text-blue-600 italic tracking-tighter">PREMIUM ADMIN</h2>
            <nav class="flex lg:flex-col gap-2 w-full">
                <button onclick="tab('dash')" id="btn-dash" class="flex-1 lg:w-full text-center lg:text-left p-4 rounded-xl font-bold active-btn">📊 Dashboard</button>
                <button onclick="tab('links')" id="btn-links" class="flex-1 lg:w-full text-center lg:text-left p-4 rounded-xl font-bold text-slate-500">🔗 Links</button>
                <button onclick="tab('ads')" id="btn-ads" class="flex-1 lg:w-full text-center lg:text-left p-4 rounded-xl font-bold text-slate-500">💰 Ads</button>
                <button onclick="tab('banner_ads')" id="btn-banner_ads" class="flex-1 lg:w-full text-center lg:text-left p-4 rounded-xl font-bold text-slate-500">🖼️ Banners</button>
                <button onclick="tab('partners')" id="btn-partners" class="flex-1 lg:w-full text-center lg:text-left p-4 rounded-xl font-bold text-slate-500">📢 Partners</button>
                <button onclick="tab('config')" id="btn-config" class="flex-1 lg:w-full text-center lg:text-left p-4 rounded-xl font-bold text-slate-500">⚙️ Settings</button>
                <a href="/logout" class="flex-1 lg:w-full text-center lg:text-left p-4 rounded-xl font-bold text-red-500 hover:bg-red-50 mt-4 lg:mt-10 border border-red-100 lg:border-none">🚪 Logout</a>
            </nav>
        </div>

        <div class="flex-1 p-6 lg:p-12 overflow-y-auto">
            <div id="dash" class="tab-content active space-y-8">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="bg-blue-600 p-8 rounded-[40px] text-white shadow-xl"><p class="text-xs font-bold opacity-70">TOTAL VIEWS</p><h3 class="text-5xl font-black">{{total_views}}</h3></div>
                    <div class="bg-emerald-500 p-8 rounded-[40px] text-white shadow-xl"><p class="text-xs font-bold opacity-70">TODAY'S VIEWS</p><h3 class="text-5xl font-black">{{today_views}}</h3></div>
                    <div class="bg-white p-8 rounded-[40px] border shadow-sm"><p class="text-xs font-bold text-slate-400">TOTAL LINKS</p><h3 class="text-5xl font-black text-slate-800">{{all_urls|length}}</h3></div>
                </div>
                <div class="grid grid-cols-1 xl:grid-cols-2 gap-8">
                    <div class="bg-white p-8 rounded-[40px] border shadow-sm"><h4 class="font-black mb-6 uppercase text-slate-400 text-sm">Traffic Trend</h4><canvas id="trafficChart"></canvas></div>
                    <div class="bg-white p-8 rounded-[40px] border shadow-sm">
                        <h4 class="font-black mb-6 uppercase text-slate-400 text-sm">Devices & Countries</h4>
                        <div class="grid grid-cols-2 gap-4">
                            <div><p class="text-xs font-bold text-blue-600 mb-2">DEVICES</p>{% for d in devices %}<div class="bg-slate-50 p-2 rounded-lg text-xs mb-1 flex justify-between"><span>{{d._id}}</span><b>{{d.count}}</b></div>{% endfor %}</div>
                            <div><p class="text-xs font-bold text-orange-600 mb-2">COUNTRIES</p>{% for c in countries %}<div class="bg-slate-50 p-2 rounded-lg text-xs mb-1 flex justify-between"><span>{{c._id}}</span><b>{{c.count}}</b></div>{% endfor %}</div>
                        </div>
                    </div>
                </div>
            </div>

            <div id="links" class="tab-content">
                <div class="bg-white rounded-[40px] border shadow-sm overflow-x-auto">
                    <table class="w-full text-left text-sm"><thead class="bg-slate-50 font-bold uppercase text-slate-400"><tr><th class="p-6">Link</th><th class="p-6">Original URL</th><th class="p-6">Clicks</th></tr></thead>
                    <tbody class="divide-y font-bold">{% for u in all_urls %}<tr><td class="p-6 text-blue-600">/{{u.short_code}}</td><td class="p-6 truncate max-w-xs text-slate-500">{{u.long_url}}</td><td class="p-6">{{u.clicks}}</td></tr>{% endfor %}</tbody></table>
                </div>
            </div>

            <div id="ads" class="tab-content space-y-8">
                <div class="bg-white p-10 rounded-[50px] border shadow-sm">
                    <h4 class="font-black mb-6">Manage Direct Ad Links</h4>
                    <form action="/admin/add_ad_link" method="POST" class="flex flex-col md:flex-row gap-4 mb-8">
                        <input type="url" name="ad_url" placeholder="Paste Direct Link URL..." required class="flex-1 p-4 bg-slate-50 rounded-2xl">
                        <button class="bg-blue-600 text-white px-10 py-4 rounded-2xl font-black">ADD LINK</button>
                    </form>
                    <div class="space-y-3">{% for l in ad_links %}<div class="bg-slate-50 p-5 rounded-3xl flex justify-between items-center"><span>{{l.url}}</span><a href="/admin/delete_ad_link/{{l._id}}" class="text-red-500 font-bold">DELETE</a></div>{% endfor %}</div>
                </div>
            </div>

            <div id="banner_ads" class="tab-content space-y-8">
                <div class="bg-white p-10 rounded-[50px] border shadow-sm">
                    <h4 class="font-black mb-6 italic">Manage Banner Ads (Unlimited)</h4>
                    <form action="/admin/add_banner" method="POST" class="flex flex-col gap-4 mb-8">
                        <textarea name="code" placeholder="Paste Ad Code (HTML/JS) Here..." required class="h-32 p-4 bg-slate-50 rounded-2xl font-mono text-sm border"></textarea>
                        <button class="bg-purple-600 text-white px-10 py-4 rounded-2xl font-black">SAVE AD CODE</button>
                    </form>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {% for b in banners %}
                        <div class="p-4 bg-slate-50 rounded-2xl border flex flex-col gap-2">
                            <code class="text-[10px] truncate block opacity-50">{{b.code}}</code>
                            <a href="/admin/delete_banner/{{b._id}}" class="text-red-500 font-bold text-xs uppercase">Delete Ad</a>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <div id="partners" class="tab-content">
                <div class="bg-white p-10 rounded-[50px] border shadow-sm">
                    <h4 class="font-black mb-6">Official Channels</h4>
                    <form action="/admin/add_channel" method="POST" class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-10">
                        <input type="text" name="name" placeholder="Name" required class="p-4 bg-slate-50 rounded-xl">
                        <input type="url" name="logo" placeholder="Logo URL" required class="p-4 bg-slate-50 rounded-xl">
                        <input type="url" name="link" placeholder="Invite Link" required class="p-4 bg-slate-50 rounded-xl">
                        <button class="bg-emerald-600 text-white rounded-xl font-bold">ADD CHANNEL</button>
                    </form>
                    <div class="grid gap-6">{% for ch in channels %}<div class="flex items-center gap-6 p-4 border-b"><img src="{{ch.logo}}" class="w-20 h-12 object-cover rounded shadow"><b>{{ch.name}}</b><a href="/admin/delete_channel/{{ch._id}}" class="ml-auto text-red-500 font-bold">DEL</a></div>{% endfor %}</div>
                </div>
            </div>

            <div id="config" class="tab-content space-y-8">
                <form action="/admin/update" method="POST" class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="bg-white p-10 rounded-[50px] shadow-sm border space-y-6">
                        <h4 class="font-black text-xl">General Settings</h4>
                        <input type="text" name="site_name" value="{{s.site_name}}" placeholder="Site Name" class="w-full p-4 bg-slate-50 rounded-2xl font-bold">
                        <div class="grid grid-cols-2 gap-4">
                            <input type="number" name="steps" value="{{s.steps}}" placeholder="Steps" class="p-4 bg-slate-50 rounded-2xl">
                            <input type="number" name="timer_seconds" value="{{s.timer_seconds}}" placeholder="Seconds" class="p-4 bg-slate-50 rounded-2xl">
                            <select name="main_theme" class="p-4 bg-slate-50 rounded-2xl">{% for k in colors %}<option value="{{k}}" {% if s.main_theme == k %}selected{% endif %}>HOME: {{k|upper}}</option>{% endfor %}</select>
                            <select name="step_theme" class="p-4 bg-slate-50 rounded-2xl">{% for k in colors %}<option value="{{k}}" {% if s.step_theme == k %}selected{% endif %}>STEP: {{k|upper}}</option>{% endfor %}</select>
                        </div>
                        <div class="bg-orange-50 p-6 rounded-3xl space-y-4">
                            <p class="text-xs font-bold text-orange-600 uppercase">API Management</p>
                            <input type="text" id="apiKey" name="api_key" value="{{s.api_key}}" class="w-full p-4 bg-white rounded-xl text-xs font-mono border outline-none">
                            <div class="flex gap-2">
                                <button type="button" onclick="copyApi()" class="flex-1 bg-white text-orange-600 py-3 rounded-lg text-xs font-bold border">COPY KEY</button>
                                <button type="button" onclick="genApi()" class="flex-1 bg-orange-600 text-white py-3 rounded-lg text-xs font-bold">REGENERATE</button>
                            </div>
                        </div>
                        <input type="text" name="admin_telegram_id" value="{{s.admin_telegram_id}}" placeholder="Telegram Chat ID" class="w-full p-4 bg-slate-50 rounded-2xl font-bold">
                        <input type="password" name="new_password" placeholder="Change Admin Password" class="w-full p-4 bg-red-50 rounded-2xl font-bold">
                    </div>
                    
                    <div class="bg-white p-10 rounded-[50px] shadow-sm border space-y-4">
                        <h4 class="font-black text-xl text-emerald-600">Monetization Scripts</h4>
                        <input type="number" name="direct_click_limit" value="{{s.direct_click_limit}}" class="w-full p-4 bg-blue-50 rounded-2xl font-bold" placeholder="Clicks per direct ad">
                        <textarea name="popunder" placeholder="Popunder Script" class="w-full h-24 p-4 bg-slate-50 rounded-xl text-xs font-mono">{{s.popunder}}</textarea>
                        <textarea name="banner" placeholder="Banner Script" class="w-full h-24 p-4 bg-slate-50 rounded-xl text-xs font-mono">{{s.banner}}</textarea>
                        <textarea name="social_bar" placeholder="Social Bar Script" class="w-full h-24 p-4 bg-slate-50 rounded-xl text-xs font-mono">{{s.social_bar}}</textarea>
                        <textarea name="native" placeholder="Native Script" class="w-full h-24 p-4 bg-slate-50 rounded-xl text-xs font-mono">{{s.native}}</textarea>
                        <button class="w-full bg-slate-900 text-white py-6 rounded-3xl font-black text-xl shadow-xl">SAVE ALL CHANGES</button>
                    </div>
                </form>
            </div>
        </div>
        <script>
            function tab(id) {
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                document.querySelectorAll('nav button').forEach(b => b.classList.remove('active-btn'));
                document.getElementById(id).classList.add('active');
                document.getElementById('btn-'+id).classList.add('active-btn');
            }
            function genApi() {
                const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
                let res = ""; for(let i=0; i<40; i++) res += chars[Math.floor(Math.random()*chars.length)];
                document.getElementById('apiKey').value = res;
            }
            function copyApi() {
                let key = document.getElementById('apiKey'); key.select();
                navigator.clipboard.writeText(key.value); alert("API Key Copied!");
            }
            new Chart(document.getElementById('trafficChart'), {
                type: 'line',
                data: { labels: {{chart_labels|tojson}}, datasets: [{ label: 'Views', data: {{chart_values|tojson}}, borderColor: '#2563eb', backgroundColor: 'rgba(37, 99, 235, 0.1)', fill: true, tension: 0.4, borderWidth: 4 }] },
                options: { responsive: true, plugins: { legend: { display: false } } }
            });
        </script>
    </body></html>
    ''', total_views=total_views, today_views=today_views, all_urls=all_urls, countries=countries, 
        devices=devices, ad_stats=ad_stats, ad_links=ad_links, banners=banners, channels=channels, s=settings, 
        colors=COLOR_MAP.keys(), chart_labels=chart_labels, chart_values=chart_values)

# --- ব্যানার অ্যাড ও ডিরেক্ট অ্যাড একশন ---
@app.route('/admin/add_banner', methods=['POST'])
def add_banner():
    if not is_logged_in(): return redirect(url_for('login'))
    code = request.form.get('code')
    if code: banners_col.insert_one({"code": code})
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_banner/<id>')
def delete_banner(id):
    if not is_logged_in(): return redirect(url_for('login'))
    banners_col.delete_one({"_id": ObjectId(id)})
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_ad_link', methods=['POST'])
def add_ad_link():
    if not is_logged_in(): return redirect(url_for('login'))
    url = request.form.get('ad_url')
    if url: ad_links_col.insert_one({"url": url})
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_ad_link/<id>')
def delete_ad_link(id):
    if not is_logged_in(): return redirect(url_for('login'))
    ad_links_col.delete_one({"_id": ObjectId(id)})
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_channel', methods=['POST'])
def add_channel():
    if not is_logged_in(): return redirect(url_for('login'))
    name, logo, link = request.form.get('name'), request.form.get('logo'), request.form.get('link')
    if logo and link: channels_col.insert_one({"name": name, "logo": logo, "link": link})
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_channel/<id>')
def delete_channel(id):
    if not is_logged_in(): return redirect(url_for('login'))
    channels_col.delete_one({"_id": ObjectId(id)})
    return redirect(url_for('admin_panel'))

@app.post('/admin/update')
def update_settings():
    if not is_logged_in(): return redirect(url_for('login'))
    d = {
        "site_name": request.form.get('site_name'),
        "admin_telegram_id": request.form.get('admin_telegram_id'),
        "steps": int(request.form.get('steps', 2)),
        "timer_seconds": int(request.form.get('timer_seconds', 10)),
        "api_key": request.form.get('api_key').strip(),
        "popunder": request.form.get('popunder'),
        "banner": request.form.get('banner'),
        "social_bar": request.form.get('social_bar'),
        "native": request.form.get('native'),
        "direct_click_limit": int(request.form.get('direct_click_limit', 1)),
        "main_theme": request.form.get('main_theme'),
        "step_theme": request.form.get('step_theme')
    }
    np = request.form.get('new_password')
    if np and len(np) > 2: d["admin_password"] = generate_password_hash(np)
    settings_col.update_one({}, {"$set": d})
    return redirect(url_for('admin_panel'))

# --- শর্ট লিংক হ্যান্ডলিং ---
@app.route('/<short_code>')
def handle_ad_steps(short_code):
    step = int(request.args.get('step', 1))
    settings = get_settings()
    url_data = urls_col.find_one({"short_code": short_code})
    if not url_data: return "404 Not Found", 404
    
    # ফাইনাল Get Link পেজ
    if step > settings['steps']:
        urls_col.update_one({"short_code": short_code}, {"$inc": {"clicks": 1}})
        track_click(short_code)
        tc = COLOR_MAP.get(settings.get('step_theme', 'blue'), COLOR_MAP['blue'])
        return render_template_string(f'''
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><script src="https://cdn.tailwindcss.com"></script></head>
        <body class="bg-slate-50 flex flex-col items-center p-6 min-h-screen text-center">
            <div class="bg-white p-12 rounded-[50px] shadow-2xl max-w-2xl w-full border-t-[16px] {tc['border']} mt-10">
                <h2 class="text-4xl font-black {tc['text']} uppercase italic mb-6">Your Link is Ready!</h2>
                <a href="{url_data['long_url']}" class="block w-full {tc['bg']} text-white py-8 rounded-[40px] font-black text-4xl uppercase shadow-xl hover:scale-105 transition">GET LINK</a>
            </div>
            {get_channels_html(settings.get('step_theme', 'blue'))}
        </body></html>
        ''')
    
    # মাঝখানের অ্যাড স্টেপগুলো
    ads = [l['url'] for l in ad_links_col.find()]
    banners = list(banners_col.find()) 
    tc = COLOR_MAP.get(settings.get('step_theme', 'blue'), COLOR_MAP['blue'])
    
    # রিয়েল স্পোর্টস নিউজ ডাইনামিক ডাটা
    sports_news = [
        {"img": "https://img.freepik.com/free-photo/soccer-ball-stadium-night_23-2148821558.jpg", "title": "IPL 2025: Grand Auction and Team Strategy Update"},
        {"img": "https://img.freepik.com/free-photo/cricket-ball-pitch_23-2148135245.jpg", "title": "Champions League: Real Madrid vs Man City Highlights"},
        {"img": "https://img.freepik.com/free-vector/modern-tennis-background-with-ball-racket_23-2148122359.jpg", "title": "Wimbledon 2025: Shocking results from today's match"},
        {"img": "https://img.freepik.com/free-photo/close-up-basketball-player_23-2148858342.jpg", "title": "NBA Season: LeBron sets new record in intense finish"}
    ]

    return render_template_string('''
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><script src="https://cdn.tailwindcss.com"></script>
    {{ s.popunder|safe }} {{ s.social_bar|safe }}
    <style> .ad-box { width: 100%; display: flex; justify-content: center; margin: 20px 0; border-radius: 20px; overflow: hidden; } .ad-box * { max-width: 100% !important; } </style>
    </head><body class="bg-slate-50 flex flex-col items-center p-6 min-h-screen">
        <div class="mb-6">{{ s.banner|safe }}</div>
        <div class="bg-white p-10 md:p-16 rounded-[50px] shadow-2xl text-center max-w-2xl w-full border-t-[16px] {{tc.border}}">
            <p class="text-xl font-black {{tc.text}} uppercase tracking-widest mb-4">Step {{step}} of {{total_steps}}</p>
            
            <div id="timer_box" class="text-7xl font-black {{tc.text}} mb-8 {{tc.light_bg}} w-40 h-40 flex items-center justify-center rounded-full mx-auto border-8 shadow-inner">{{timer}}</div>
            
            <button id="scroll_to_btn" onclick="document.getElementById('main_btn').scrollIntoView({behavior: 'smooth'})" style="display:none;" class="w-full {{tc.bg}} text-white py-6 rounded-3xl font-black text-xl uppercase mb-8 animate-bounce shadow-xl">Scroll to Continue ↓</button>

            <div id="ads_container" class="space-y-6">
                {% for b in banners %}
                    <div class="ad-box">{{ b.code|safe }}</div>
                    {% set news = sports_news|random %}
                    <div class="bg-slate-100 rounded-3xl overflow-hidden text-left border shadow-sm">
                        <img src="{{ news.img }}" class="w-full h-40 object-cover">
                        <div class="p-4"><p class="font-bold text-slate-700 leading-tight">{{ news.title }}</p></div>
                    </div>
                {% endfor %}
            </div>

            <button id="main_btn" disabled onclick="handleClick()" class="w-full bg-slate-300 text-white py-8 rounded-[40px] font-black text-3xl uppercase mt-8 opacity-50 cursor-not-allowed">Continue</button>
        </div>
        <div class="mt-4">{{ s.native|safe }}</div>{{ partners_html|safe }}
        
        <script>
            let sec = {{timer}}, ads = {{ads|tojson}}, clicks = 0, limit = {{limit}};
            const timerBox = document.getElementById('timer_box'), mainBtn = document.getElementById('main_btn'), scrollBtn = document.getElementById('scroll_to_btn');
            const iv = setInterval(() => { 
                sec--; timerBox.innerText = sec; 
                if(sec<=0) { 
                    clearInterval(iv); 
                    timerBox.style.display='none'; 
                    scrollBtn.style.display='block';
                    mainBtn.disabled = false; 
                    mainBtn.classList.remove('bg-slate-300', 'opacity-50', 'cursor-not-allowed');
                    mainBtn.classList.add('{{tc.bg}}');
                    updateBtn(); 
                } 
            }, 1000);

            function updateBtn() { mainBtn.innerText = (clicks < limit && ads.length > 0) ? "VERIFY ("+(clicks+1)+"/"+limit+")" : "CONTINUE"; }
            function handleClick() {
                if(clicks < limit && ads.length > 0) {
                    let r = ads[Math.floor(Math.random()*ads.length)];
                    fetch('/track_ajax?sc={{sc}}&ad='+encodeURIComponent(r)); window.open(r, '_blank'); clicks++; updateBtn();
                } else { window.location.href = "/{{sc}}?step="+({{step}}+1); }
            }
        </script>
    </body></html>
    ''', s=settings, step=step, total_steps=settings['steps'], timer=settings['timer_seconds'], tc=tc, ads=ads, banners=banners, sports_news=sports_news, limit=settings['direct_click_limit'], sc=short_code, partners_html=get_channels_html(settings.get('step_theme', 'blue')))

@app.route('/track_ajax')
def track_ajax():
    track_click(request.args.get('sc'), request.args.get('ad'))
    return "ok"

# --- লগইন ও রিকভারি ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in(): return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        if check_password_hash(get_settings()['admin_password'], request.form.get('password')):
            session.permanent = True
            session['logged_in'] = True; return redirect(url_for('admin_panel'))
    return render_template_string('<body style="background:#0f172a;display:flex;justify-content:center;align-items:center;height:100vh;padding:20px;"><form method="POST" style="background:white;padding:40px;border-radius:30px;text-align:center;width:100%;max-width:350px;"><h2 style="font-weight:900;margin-bottom:30px;">ADMIN LOGIN</h2><input type="password" name="password" placeholder="Key" style="width:100%;padding:15px;margin-bottom:15px;border:1px solid #ddd;border-radius:10px;text-align:center;"><button style="width:100%;padding:15px;background:#1e293b;color:white;border:none;border-radius:10px;font-weight:900;">LOGIN</button><a href="/forgot-password" style="display:block;margin-top:20px;font-size:12px;color:#3b82f6;text-decoration:none;">Forgot Passkey?</a></form></body>')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        tg_id = request.form.get('telegram_id')
        settings = get_settings()
        if tg_id == settings.get('admin_telegram_id'):
            otp = str(random.randint(100000, 999999))
            otp_col.update_one({"id": "admin_reset"}, {"$set": {"otp": otp, "expire_at": datetime.now() + timedelta(minutes=5)}}, upsert=True)
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data={"chat_id": tg_id, "text": f"🛡️ OTP: {otp}"})
            session['reset_id'] = tg_id; return redirect(url_for('verify_otp'))
    return render_template_string('<body style="background:#0f172a;display:flex;justify-content:center;align-items:center;height:100vh;"><form method="POST" style="background:white;padding:40px;border-radius:30px;width:320px;text-align:center;"><h2>Recovery</h2><input type="text" name="telegram_id" placeholder="Telegram Chat ID" required style="width:100%;padding:15px;margin:20px 0;text-align:center;"><button style="width:100%;padding:15px;background:#3b82f6;color:white;border:none;border-radius:15px;">GET OTP</button></form></body>')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if not session.get('reset_id'): return redirect('/forgot-password')
    if request.method == 'POST':
        otp = request.form.get('otp'); data = otp_col.find_one({"id": "admin_reset"})
        if data and data['otp'] == otp and data['expire_at'] > datetime.now():
            session['otp_verified'] = True; return redirect(url_for('reset_password'))
    return render_template_string('<body style="background:#0f172a;display:flex;justify-content:center;align-items:center;height:100vh;"><form method="POST" style="background:white;padding:40px;border-radius:30px;width:320px;text-align:center;"><h2>Verify OTP</h2><input type="text" name="otp" placeholder="ENTER OTP" required style="width:100%;padding:15px;margin:20px 0;text-align:center;font-size:24px;"><button style="width:100%;padding:15px;background:#10b981;color:white;border:none;border-radius:15px;">VERIFY</button></form></body>')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified'): return redirect('/forgot-password')
    if request.method == 'POST':
        pw = request.form.get('password')
        settings_col.update_one({}, {"$set": {"admin_password": generate_password_hash(pw)}})
        session.clear(); return 'SUCCESS! <a href="/login">LOGIN NOW</a>'
    return render_template_string('<body style="background:#0f172a;display:flex;justify-content:center;align-items:center;height:100vh;"><form method="POST" style="background:white;padding:40px;border-radius:30px;width:320px;"><h2 style="text-align:center;">NEW PASSWORD</h2><input type="password" name="password" required placeholder="New Password" style="width:100%;padding:15px;margin:20px 0;"><button style="width:100%;padding:15px;background:#1e293b;color:white;border:none;border-radius:15px;">UPDATE</button></form></body>')

if __name__ == '__main__':
    app.run(debug=True)
