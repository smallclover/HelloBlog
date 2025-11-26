import requests
import re
import feedparser
import time
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import timedelta

# 仓库 README 的 Raw 地址
README_URL = "https://raw.githubusercontent.com/smallclover/HelloBlog/main/README.md"

# 伪装浏览器 Header，防止被拦截
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
    """表格解析函数，带调试信息"""
    print(f"DEBUG: 获取到的 README 长度为 {len(content)} 字符")
    
    blogs = []
    lines = content.split('\n')
    
    # 找到表格的列索引映射
    # 假设标准结构: | 博客名称 | 链接 | ... | RSS |
    # 实际上我们只需要确定 Name(第1列), Link(第2列), RSS(第9列)
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # 1. 跳过非表格行
        if not line.startswith("|"):
            continue
            
        # 2. 跳过分割线 (---|---)
        if "---" in line:
            continue
            
        # 3. 跳过表头 (包含 "博客名称" 字样)
        if "博客名称" in line and "链接" in line:
            print(f"DEBUG: 跳过表头行: {line[:30]}...")
            continue
            
        # --- 开始解析数据行 ---
        
        # 按 | 分割，并去除每一项的首尾空格
        cols = [c.strip() for c in line.split('|')]
        
        # split('|') 后，如果行首尾都有 |，列表的第一个和最后一个元素通常是空字符串
        # 例如: "| A | B |" -> ['', 'A', 'B', '']
        # 去除空字符串，保留有效内容
        clean_cols = [c for c in cols if c]
        
        # 现在的 clean_cols索引: 0=名称, 1=链接, ..., 8=RSS (如果没缺列)
        if len(clean_cols) < 2:
            # 列太少，肯定不是有效数据
            continue

        try:
            # --- 提取名称 ---
            # 格式可能是 "**Name**" 或 "Name"
            name_raw = clean_cols[0]
            # 去除 Markdown 加粗符号
            name = name_raw.replace('**', '').strip()
            
            # --- 提取链接 ---
            # 格式通常是 "[url](url)"
            link_raw = clean_cols[1]
            link_match = re.search(r'\((http.*?)\)', link_raw)
            if link_match:
                link = link_match.group(1)
            else:
                # 尝试直接匹配 http，防止有些人直接写链接没加 []()
                link_simple = re.search(r'(http[s]?://\S+)', link_raw)
                link = link_simple.group(1) if link_simple else None
            
            # --- 提取 RSS (假设在最后一列 或者 第9列) ---
            rss = None
            # 你的表格大概有9列数据。RSS在最后一列。
            # 检查是否有 RSS 列 (通常是最后一列，或者包含 'feed'/'rss'/'xml' 的链接)
            if len(clean_cols) >= 9:
                rss_raw = clean_cols[8] # 第9列
                rss_match = re.search(r'\((http.*?)\)', rss_raw)
                if rss_match:
                    rss = rss_match.group(1)
            
            # 如果解析到了名字和链接，就存入结果
            if name and link:
                # print(f"DEBUG: 成功解析 - {name}") # 如果太多可以注释掉
                blogs.append({
                    "name": name,
                    "link": link,
                    "rss": rss
                })
                
        except Exception as e:
            print(f"DEBUG: 解析行出错 '{line}': {e}")
            continue

    print(f"DEBUG: 解析完成，共找到 {len(blogs)} 个博客")
    return blogs

# --- 核心抓取逻辑 ---

def get_date_from_rss(rss_url):
    """策略1: 通过 RSS 获取"""

    print(f"DEBUG: 尝试从 rss 获取日期: {rss_url}")

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
    """策略2: 猜测并读取 sitemap.xml"""
    print(f"DEBUG: 尝试从 sitemap.xml 获取日期: {site_url}")
    # 常见的 sitemap 地址
    sitemap_paths = ['/sitemap.xml', '/sitemap_index.xml', '/atom.xml']
    
    for path in sitemap_paths:
        target_url = urljoin(site_url, path)
        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=5)
            if resp.status_code != 200: continue
            
            # 简单解析 XML 寻找 <lastmod>
            soup = BeautifulSoup(resp.content, 'xml')
            lastmods = soup.find_all('lastmod')
            dates = []
            for lm in lastmods:
                text = lm.text[:10] # 截取 YYYY-MM-DD
                dates.append(text)
            
            if dates:
                dates.sort(reverse=True) # 排序取最新的
                return dates[0]
        except:
            continue
    return None
def get_date_by_brute_force(site_url):
    """
    使用 headless 浏览器（Playwright）渲染页面，然后在渲染后的 HTML 中搜索日期字符串。
    如果 Playwright 不可用或渲染失败，则回退到 requests 获取 HTML 的方式。
    支持格式：2024-11-25, 2024/11/25, 2024.11.25, 2024年11月25日
    """
    print(f"   [暴力搜索] 正在使用 headless 渲染: {site_url} ...")
    html = None

    # 先尝试用 Playwright 渲染（更可靠：能抓到 JS 渲染的内容）
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(extra_http_headers={"User-Agent": HEADERS["User-Agent"]})
            # 尝试跳转并等待网络空闲（最多 15s）
            try:
                page.goto(site_url, timeout=15000, wait_until='networkidle')
            except Exception:
                # 如果 networkidle 超时，则尝试 load
                try:
                    page.goto(site_url, timeout=15000, wait_until='load')
                except Exception as e:
                    print(f"   [Playwright goto Error] {e}")
            # 可选地等待一些常见元素加载（这里不强制）
            html = page.content()
            browser.close()
            print("   [Info] Playwright 渲染成功，取得页面内容长度:", len(html) if html else 0)
    except Exception as e:
        print(f"   [Playwright Unavailable or Error] {e}")
        # 回退：用 requests 获取原始 HTML（可能抓不到 JS 渲染内容）
        try:
            resp = requests.get(site_url, headers=HEADERS, timeout=10)
            resp.encoding = resp.apparent_encoding
            html = resp.text
            print("   [Info] 回退到 requests 获取 HTML，长度:", len(html) if html else 0)
        except Exception as e2:
            print(f"   [Requests Error] {e2}")
            return None

    if not html:
        return None

    # 下面是正则匹配逻辑（和你原来的实现类似，但更稳健）
    try:
        # 模式 A: 纯数字分隔 (YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD)
        pattern_common = r'(202[3-5])[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12][0-9]|3[01])'
        # 模式 B: 中文格式 (2024年5月20日 / 2024年05月20日)
        pattern_cn = r'(202[3-5])年(0?[1-9]|1[0-2])月(0?[1-9]|[12][0-9]|3[01])日'

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

        if not found_dates:
            # 进一步尝试匹配类似 "2024年 05 月 20 日" 带空格的中文格式
            pattern_cn_space = r'(202[3-5])\s*年\s*(0?[1-9]|1[0-2])\s*月\s*(0?[1-9]|[12][0-9]|3[01])\s*日'
            for match in re.findall(pattern_cn_space, html):
                year, month, day = match
                month = month.zfill(2)
                day = day.zfill(2)
                date_str = f"{year}-{month}-{day}"
                found_dates.add(date_str)

        if not found_dates:
            return None

        sorted_dates = sorted(list(found_dates), reverse=True)
        latest_date = sorted_dates[0]

        current_year = datetime.now().year
        if int(latest_date.split('-')[0]) > current_year + 1:
            if len(sorted_dates) > 1:
                return sorted_dates[1]
            return None

        return latest_date

    except Exception as e:
        print(f"   [Regex Error] {e}")
        return None

def check_update(blog):
    # 1. 优先 RSS (最准)
    if blog.get('rss'):
        date = get_date_from_rss(blog['rss'])
        if date: return date

    # 2. 其次 Sitemap (通常很准)
    date = get_date_from_sitemap(blog['link'])
    if date: return date
    
    # 3. 最后：暴力搜 HTML (稍微慢点，但能兜底)
    # 直接调用上面写的新函数
    date = get_date_by_brute_force(blog['link'])
    if date: 
        return date # 不需要打印 [HTML]，函数里已经打印了
        
    return "Unknown"

def calculate_status_string(date_str):
    """
    根据日期计算新的“更新状态”字符串。
    如果三个月内有更新 -> '🔥 活跃'
    否则 -> '最后更新YYYY年MM月'
    """
    if date_str == "Unknown":
        return '⚫ 停更' # 如果抓取失败，显示停更或保持原状（这里选择显示停更）
        
    try:
        # 将抓取的日期字符串转换为 datetime 对象
        last_update_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        today = datetime.now().date()
        
        # 定义三个月前的日期（约90天）
        three_months_ago = today - timedelta(days=90)

        if last_update_date >= three_months_ago:
            return '🔥 活跃'
        else:
            # 格式化为 XXXX年XX月
            return f"最后更新{last_update_date.year}年{last_update_date.month:02d}月"
            
    except ValueError:
        return '⚫ 停更'

def update_readme_content(original_content, update_results):
    """
    遍历原始 README，替换表格中第 7 列（更新状态）的内容。
    """
    new_lines = []
    
    # 匹配 Markdown 表格行的通用正则表达式，用于识别数据行
    # 注意：Markdown 表格行通常以 | 开头
    # 我们要匹配并保留 | Name | Link | Content | Author | Tags | Access | [Status] | Rec | RSS |
    # 替换目标是 Status 所在的内容
    
    for line in original_content.split('\n'):
        # 检查是否为有效的数据行 (不包含 '---', 不包含 '博客名称', 以 | 开头)
        if line.strip().startswith('|') and '---' not in line and '博客名称' not in line:
            
            cols = [c.strip() for c in line.split('|')]
            # 确保列数足够
            if len(cols) < 10: 
                new_lines.append(line)
                continue
            
            # 提取名称 (从第 1 列)
            # 名字在第 1 列，可能包含 **加粗**
            name_raw = cols[1].replace('**', '').strip()
            
            if name_raw in update_results:
                
                # 1. 计算新的状态字符串
                date_str = update_results[name_raw]
                new_status = calculate_status_string(date_str)
                
                # 2. 构造新的行
                # 更新状态在第 7 列 (cols 列表索引 7)
                
                # 替换前需要处理 cols[7] 的内容，避免影响其他列的对齐
                old_status_raw = cols[7]
                
                # 确保替换后的内容不会太长，导致列对齐出问题，但这里保持简单
                cols[7] = new_status
                
                # 重新拼接行 (注意：Markdown 表格的首尾需要保留空的 |)
                new_line = '|' + '|'.join(cols) + '|'
                
                # 为了保持表格对齐，需要确保每列的宽度与原 README 匹配，
                # 但手动维护宽度非常复杂。我们这里使用简单的 '|' 拼接，
                # 依赖 Markdown 渲染器自动调整对齐。
                
                new_lines.append(new_line)
                continue # 已处理，跳过后续
        
        # 非数据行（标题、分隔线、非表格内容等）保持不变
        new_lines.append(line)

    return '\n'.join(new_lines)

def update_timestamp(content):
    """
    更新 README 顶部的“更新时间”。
    注意：GitHub Actions 默认运行在 UTC 时间，此时间为 UTC 时间。
    """
    
    # 格式化当前时间为 YYYY/MM/DD HH:MM
    # GitHub Actions 运行在 UTC 时间，这里获取的是 UTC 时间
    now = datetime.now() 
    current_time_str = now.strftime("%Y/%m/%d %H:%M")
    
    # 正则表达式：
    # 目标：(<p align="center">\s*<span>更新时间：) 后面跟着的内容 (.*?) (</span>\s*</p>)
    # 使用非贪婪匹配 (.*?) 来确保只替换 span 标签内的内容
    pattern = r'(<p\s+align="center">\s*<span>更新时间：).*?(</span>\s*</p>)'
    
    # 替换字符串：\1 是匹配到的第一个括号内容，然后是新的时间，\2 是第二个括号内容
    replacement = r'\1' + current_time_str + r'\2'
    
    print(f"DEBUG: 正在更新时间戳为: {current_time_str}")
    
    # 执行替换 (re.DOTALL 确保 . 能匹配换行符，以防 span 标签跨行)
    updated_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    return updated_content

def main():
    global update_results
    
    # 1. 获取原始 README 内容
    original_content = fetch_readme()
    if not original_content: return

    # 2. 解析博客列表
    blogs = parse_blog_list(original_content)
    print(f"找到 {len(blogs)} 个博客，开始检查更新...\n")
    
    # 3. 抓取并存储更新日期
    for blog in blogs:
        last_update = check_update(blog)
        # 只有抓取到合法日期（YYYY-MM-DD）才更新字典
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
    
    # 5. 【新增步骤】更新时间戳
    print("开始更新顶部的运行时间戳...")
    final_content = update_timestamp(updated_content_table)
    
    # 6. 覆盖写入原始文件
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(final_content)
        
    print("\n✅ README.md 已更新。")

if __name__ == "__main__":
    main()