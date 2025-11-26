import requests
import re
import feedparser
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# 仓库 README 的 Raw 地址
README_URL = "https://raw.githubusercontent.com/smallclover/HelloBlog/main/README.md"

# 伪装浏览器 Header
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

update_results = {}

def fetch_readme():
    try:
        resp = requests.get(README_URL, headers=HEADERS)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"获取 README 失败: {e}")
        return None

def parse_blog_list(content):
    """解析表格提取博客信息"""
    print(f"DEBUG: 获取到的 README 长度为 {len(content)} 字符")
    blogs = []
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        # 只要是表格行且不是分割线
        if line.startswith("|") and "---" not in line and "博客名称" not in line:
            # 提取有效列（去除空字符串）
            cols = [c.strip() for c in line.split('|') if c.strip()]
            
            if len(cols) < 2: continue

            try:
                # 第1列是名称，第2列是链接，第9列是RSS
                name_raw = cols[0]
                name = name_raw.replace('**', '').strip()
                
                link_raw = cols[1]
                link_match = re.search(r'\((http.*?)\)', link_raw)
                link = link_match.group(1) if link_match else cols[1] # 简单容错
                
                rss = None
                if len(cols) >= 9:
                    rss_raw = cols[8]
                    rss_match = re.search(r'\((http.*?)\)', rss_raw)
                    rss = rss_match.group(1) if rss_match else None
                
                if name and link:
                    blogs.append({"name": name, "link": link, "rss": rss})
            except Exception:
                continue
    return blogs

# --- 抓取逻辑 (保持不变) ---
def get_date_from_rss(rss_url):
    if not rss_url: return None
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None
        dt = feed.entries[0].get('published_parsed') or feed.entries[0].get('updated_parsed')
        if dt: return time.strftime('%Y-%m-%d', dt)
    except: pass
    return None

def get_date_from_sitemap(site_url):
    sitemap_paths = ['/sitemap.xml', '/sitemap_index.xml', '/atom.xml']
    for path in sitemap_paths:
        target_url = urljoin(site_url, path)
        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=5)
            if resp.status_code != 200: continue
            soup = BeautifulSoup(resp.content, 'xml')
            lastmods = soup.find_all('lastmod')
            dates = [lm.text[:10] for lm in lastmods]
            if dates:
                dates.sort(reverse=True)
                return dates[0]
        except: continue
    return None

def get_date_by_brute_force(site_url):
    # 这里直接使用 requests 回退方案，省略 Playwright 以简化代码
    try:
        resp = requests.get(site_url, headers=HEADERS, timeout=10)
        resp.encoding = resp.apparent_encoding
        html = resp.text
        
        pattern_common = r'(202[3-5])[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12][0-9]|3[01])'
        pattern_cn = r'(202[3-5])年(0?[1-9]|1[0-2])月(0?[1-9]|[12][0-9]|3[01])日'
        
        found_dates = set()
        for match in re.findall(pattern_common, html):
            found_dates.add(f"{match[0]}-{match[1]}-{match[2]}")
        for match in re.findall(pattern_cn, html):
            found_dates.add(f"{match[0]}-{match[1].zfill(2)}-{match[2].zfill(2)}")
            
        if not found_dates: return None
        sorted_dates = sorted(list(found_dates), reverse=True)
        return sorted_dates[0]
    except: return None

def check_update(blog):
    print(f"正在检查: {blog['name']} ... ", end="", flush=True)
    
    date = get_date_from_rss(blog.get('rss'))
    if date: 
        print(f"[RSS] {date}")
        return date
        
    date = get_date_from_sitemap(blog['link'])
    if date:
        print(f"[Sitemap] {date}")
        return date
        
    date = get_date_by_brute_force(blog['link'])
    if date:
        print(f"[HTML] {date}")
        return date
        
    print("❌ 无法获取")
    return "Unknown"

def calculate_status_string(date_str):
    if date_str == "Unknown": return '⚫ 停更'
    try:
        last_update = datetime.strptime(date_str, '%Y-%m-%d').date()
        if last_update >= (datetime.now().date() - timedelta(days=90)):
            return '🔥 活跃'
        else:
            return f"最后更新{last_update.year}年{last_update.month:02d}月"
    except: return '⚫ 停更'

# --- 关键修复 1: 表格重组 ---
def update_readme_content(original_content, update_results):
    new_lines = []
    lines = original_content.split('\n')
    
    for line in lines:
        stripped = line.strip()
        # 判断是否为数据行：以 | 开头，且不包含 --- 分割线，且不是表头
        if stripped.startswith('|') and '---' not in stripped and '博客名称' not in stripped:
            
            # 1. 提取所有单元格内容（去除空字符串，避免 || 问题）
            cols = [c.strip() for c in stripped.split('|') if c.strip()]
            
            # 确保列数足够（你的表格有9列）
            if len(cols) >= 9:
                # 第1列是名称
                name_raw = cols[0].replace('**', '').strip()
                
                # 如果该博客有更新结果
                if name_raw in update_results:
                    new_status = calculate_status_string(update_results[name_raw])
                    # 第7列是状态 (索引6)
                    cols[6] = new_status
                
                # 2. 重新拼接表格行
                # 格式：| Col1 | Col2 | ... |
                # 这样可以保证左右两边各只有一个 |，且内容有空格缓冲
                new_line = "| " + " | ".join(cols) + " |"
                new_lines.append(new_line)
            else:
                # 如果列数不对，原样放回（可能是破损行）
                new_lines.append(line)
        else:
            # 非表格行原样放回
            new_lines.append(line)
            
    return '\n'.join(new_lines)

# --- 关键修复 2: 时间戳覆盖 ---
def update_timestamp(content):
    now = datetime.now()
    # 格式化时间
    current_time_str = now.strftime("%Y/%m/%d %H:%M")
    
    # 构造标准的 HTML 标签
    new_html_line = f'<p align="center"><span>更新时间：{current_time_str}</span></p>'
    
    new_lines = []
    lines = content.split('\n')
    
    time_updated = False
    for line in lines:
        # 只要行里包含 "更新时间"，或者是那个破损的 "P25/11/..."
        # 我们就直接整行替换掉，确保修复格式
        if "更新时间" in line or (line.strip().startswith("P2") and "</span>" in line):
            new_lines.append(new_html_line)
            time_updated = True
        else:
            new_lines.append(line)
            
    return '\n'.join(new_lines)

def main():
    global update_results
    original_content = fetch_readme()
    if not original_content: return

    blogs = parse_blog_list(original_content)
    
    for blog in blogs: 
        last_update = check_update(blog)
        if last_update != "Unknown":
            update_results[blog['name']] = last_update

    print("\n开始更新 README...")
    
    # 1. 更新表格
    content_step1 = update_readme_content(original_content, update_results)
    
    # 2. 更新时间戳
    final_content = update_timestamp(content_step1)
    
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(final_content)
        
    print("✅ README.md 已修复并更新。")

if __name__ == "__main__":
    main()