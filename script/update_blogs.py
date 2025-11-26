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

# 全局变量用于存储抓取结果 {博客名称: 'YYYY-MM-DD'}
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
    """表格解析函数 (保持不变，已在你那调试通过)"""
    print(f"DEBUG: 获取到的 README 长度为 {len(content)} 字符")
    
    blogs = []
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        
        if not line.startswith("|") or "---" in line or "博客名称" in line and "链接" in line:
            continue
            
        # --- 开始解析数据行 ---
        cols = [c.strip() for c in line.split('|')]
        clean_cols = [c for c in cols if c]
        
        if len(clean_cols) < 2:
            continue

        try:
            name_raw = clean_cols[0]
            name = name_raw.replace('**', '').strip()
            
            link_raw = clean_cols[1]
            link_match = re.search(r'\((http.*?)\)', link_raw)
            if link_match:
                link = link_match.group(1)
            else:
                link_simple = re.search(r'(http[s]?://\S+)', link_raw)
                link = link_simple.group(1) if link_simple else None
            
            rss = None
            if len(clean_cols) >= 9:
                rss_raw = clean_cols[8]
                rss_match = re.search(r'\((http.*?)\)', rss_raw)
                if rss_match:
                    rss = rss_match.group(1)
            
            if name and link:
                blogs.append({
                    "name": name,
                    "link": link,
                    "rss": rss
                })
        except Exception as e:
            # print(f"DEBUG: 解析行出错 '{line}': {e}") # 避免过多打印
            continue

    print(f"DEBUG: 解析完成，共找到 {len(blogs)} 个博客")
    return blogs

# --- 核心抓取逻辑（省略，保持不变） ---
def get_date_from_rss(rss_url):
    # ... (与你提供的代码一致)
    if not rss_url: return None
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None
        dt = feed.entries[0].get('published_parsed') or feed.entries[0].get('updated_parsed')
        if dt: return time.strftime('%Y-%m-%d', dt)
    except:
        pass
    return None

def get_date_from_sitemap(site_url):
    # ... (与你提供的代码一致)
    sitemap_paths = ['/sitemap.xml', '/sitemap_index.xml', '/atom.xml']
    for path in sitemap_paths:
        target_url = urljoin(site_url, path)
        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=5)
            if resp.status_code != 200: continue
            soup = BeautifulSoup(resp.content, 'xml')
            lastmods = soup.find_all('lastmod')
            dates = []
            for lm in lastmods:
                text = lm.text[:10]
                dates.append(text)
            if dates:
                dates.sort(reverse=True)
                return dates[0]
        except:
            continue
    return None

def get_date_by_brute_force(site_url):
    # ... (与你提供的代码一致)
    html = None
    # 尝试用 requests 获取原始 HTML
    try:
        resp = requests.get(site_url, headers=HEADERS, timeout=10)
        resp.encoding = resp.apparent_encoding
        html = resp.text
    except Exception as e2:
        # print(f"   [Requests Error] {e2}") # 避免过多打印
        return None

    if not html:
        return None
    try:
        pattern_common = r'(202[3-5])[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12][0-9]|3[01])'
        pattern_cn = r'(202[3-5])年(0?[1-9]|1[0-2])月(0?[1-9]|[12][0-9]|3[01])日'
        pattern_cn_space = r'(202[3-5])\s*年\s*(0?[1-9]|1[0-2])\s*月\s*(0?[1-9]|[12][0-9]|3[01])\s*日'

        found_dates = set()
        
        for match in re.findall(pattern_common, html):
            date_str = f"{match[0]}-{match[1]}-{match[2]}"
            found_dates.add(date_str)
        for match in re.findall(pattern_cn, html):
            year, month, day = match
            month = month.zfill(2)
            day = day.zfill(2)
            date_str = f"{year}-{month}-{day}"
            found_dates.add(date_str)
        for match in re.findall(pattern_cn_space, html):
            year, month, day = match
            month = month.zfill(2)
            day = day.zfill(2)
            date_str = f"{year}-{month}-{day}"
            found_dates.add(date_str)

        if not found_dates: return None

        sorted_dates = sorted(list(found_dates), reverse=True)
        latest_date = sorted_dates[0]

        current_year = datetime.now().year
        # 简单过滤未来时间
        if int(latest_date.split('-')[0]) > current_year + 1:
            if len(sorted_dates) > 1: return sorted_dates[1]
            return None

        return latest_date

    except Exception:
        return None

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
# ----------------------------------------------------------------

def calculate_status_string(date_str):
    # ... (保持不变)
    if date_str == "Unknown":
        return '⚫ 停更' 
        
    try:
        last_update_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        today = datetime.now().date()
        three_months_ago = today - timedelta(days=90)

        if last_update_date >= three_months_ago:
            return '🔥 活跃'
        else:
            return f"最后更新{last_update_date.year}年{last_update_date.month:02d}月"
            
    except ValueError:
        return '⚫ 停更'

# --- 重点修正函数：解决表格错位问题 ---
def update_readme_content(original_content, update_results):
    """
    遍历原始 README，替换表格中第 7 列（更新状态）的内容。
    **使用正则替换来保持原始表格的对齐和空格。**
    """
    new_lines = []
    
    # 匹配 Name 所在的加粗格式，用于识别数据行
    name_pattern = r'\*\*([^\*]+)\*\*'
    
    for line in original_content.split('\n'):
        
        # 检查是否为有效的数据行 (不包含 '---', 不包含 '博客名称', 以 | 开头)
        if line.strip().startswith('|') and '---' not in line and '博客名称' not in line:
            
            # 1. 尝试提取博客名称，用于查找更新结果
            name_match = re.search(name_pattern, line)
            if not name_match:
                # 再次尝试不加粗的名称匹配，以防万一
                cols_check = [c.strip() for c in line.split('|')]
                if len(cols_check) > 1:
                    name_raw = cols_check[1].strip()
                    name_raw = name_raw.replace('**', '').strip()
                else:
                    new_lines.append(line)
                    continue

            name_raw = name_match.group(1).strip() if name_match else name_raw

            if name_raw in update_results:
                
                # 2. 计算新的状态字符串
                date_str = update_results[name_raw]
                new_status = calculate_status_string(date_str)
                
                # 3. 找到并替换状态列
                # 表格行结构：| Col 1 | Col 2 | Col 3 | Col 4 | Col 5 | Col 6 | Col 7 | Col 8 | Col 9 |
                # 状态列是第 7 列 (索引 7)
                
                # 使用非贪婪匹配来分割表格内容
                parts = line.split('|')
                
                # 原始行：'' [0] | Col 1 [1] | Col 2 [2] | ... | Col 7 [7] | Col 8 [8] | Col 9 [9] | '' [10]
                # 状态在索引 7
                if len(parts) > 7:
                    # 获取第 7 列的原始内容 (包含对齐空格)
                    old_status_raw = parts[7]
                    
                    # 替换内容：用新状态替换原始状态，同时保持两侧的空格和对齐
                    # 例如: '    🟡 偶尔更新 ' -> '    🔥 活跃 '
                    
                    # 构造新的第 7 列内容：
                    # 目标：将新的状态字符串居中或左对齐填入原来的长度中
                    
                    # 简单粗暴的方式：替换掉第 7 列的内容，依赖渲染器对齐
                    # 为了尽可能保持原始对齐，我们用原内容的长度进行填充（这是一个近似值）
                    new_cell_content = new_status
                    
                    # 尝试保留两侧空格（如果原始内容有）
                    left_padding = re.match(r'^\s*', old_status_raw).group(0)
                    right_padding = re.search(r'\s*$', old_status_raw).group(0)
                    
                    parts[7] = f"{left_padding}{new_status}{right_padding}"
                    
                    # 重新拼接行，注意：join 从 parts[1] 到 parts[-2]
                    # 并在首尾加上 |
                    new_line = '|' + '|'.join(parts[1:-1]) + '|'
                    new_lines.append(new_line)
                    continue # 已处理，跳过后续
        
        # 非数据行（标题、分隔线、非表格内容等）保持不变
        new_lines.append(line)

    return '\n'.join(new_lines)

# --- 重点修正函数：解决时间戳格式问题 ---
def update_timestamp(content):
    """
    更新 README 顶部的“更新时间”。
    修正：时间格式为 YYYY/MM/DD HH:MM。
    """
    
    # 修正时间格式：匹配 README 中的格式 YYYY/MM/DD HH:MM
    now = datetime.now()
    # 如果在 GitHub Actions 中运行，通常需要加上时区调整，但这里先保持简单的本地时间格式
    current_time_str = now.strftime("%Y/%m/%d %H:%M") 
    
    # 正则表达式：查找 "更新时间：" 后面的日期和时间
    # 目标：匹配并替换 '更新时间：' 后面的所有内容直到行尾
    
    # 修正你的 README 结构：它可能不在 <p> 或 <span> 里，而是在 Markdown 文本中
    # 假设它是这样的一行：更新时间：2025/11/25 18:00
    
    # 尝试匹配 "更新时间：" 这一句
    pattern = r'(更新时间：).*?$'
    replacement = r'\1' + current_time_str
    
    print(f"DEBUG: 正在尝试更新时间戳为: {current_time_str}")
    
    # 逐行检查并替换 (不使用 re.DOTALL)
    updated_lines = []
    replaced = False
    
    for line in content.split('\n'):
        if '更新时间：' in line:
            # 找到目标行，进行替换
            new_line = re.sub(pattern, replacement, line, flags=re.MULTILINE)
            updated_lines.append(new_line)
            replaced = True
        else:
            updated_lines.append(line)
            
    # 如果你的时间戳是 HTML 格式 (如你代码中的原始正则所示)，请改回：
    # pattern_html = r'(<p\s+align="center">\s*<span>更新时间：).*?(</span>\s*</p>)'
    # updated_content = re.sub(pattern_html, replacement_html, content, flags=re.DOTALL)
    
    if not replaced:
        print("DEBUG: 未找到 '更新时间：' 标签，时间戳未更新。")

    return '\n'.join(updated_lines)

# --- 主函数保持不变 ---
def main():
    global update_results
    
    # 1. 获取原始 README 内容
    original_content = fetch_readme()
    if not original_content: return

    # 2. 解析博客列表
    blogs = parse_blog_list(original_content)
    # print(f"找到 {len(blogs)} 个博客，开始检查更新...\n")
    
    # 3. 抓取并存储更新日期
    for blog in blogs:
        last_update = check_update(blog)
        if last_update != "Unknown":
            update_results[blog['name']] = last_update
        
    print("\n" + "="*50)
    print(f"检查完成，共成功获取 {len(update_results)} 个博客的更新时间。")
    print("="*50)

    # 4. 更新 README 内容 (表格状态)
    updated_content_table = original_content
    if update_results:
        print("开始更新表格状态...")
        updated_content_table = update_readme_content(original_content, update_results)
    
    # 5. 更新时间戳
    print("开始更新顶部的运行时间戳...")
    final_content = update_timestamp(updated_content_table)
    
    # 6. 覆盖写入原始文件
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(final_content)
        
    print("\n✅ README.md 已更新。")

if __name__ == "__main__":
    # 注意：请确保已经安装了 requests, feedparser, beautifulsoup4
    # 如果需要 Playwright 的性能，请确保安装并初始化 Playwright：
    # pip install playwright && playwright install
    main()