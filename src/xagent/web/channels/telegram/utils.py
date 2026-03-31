import html
import re


def markdown_to_tg_html(text: str) -> str:
    """Convert basic Markdown to Telegram-supported HTML."""
    if not text:
        return ""

    # First, escape HTML special characters to prevent parsing errors
    text = html.escape(text)

    # Replace code blocks: ```lang\ncode\n```
    # We use <pre><code class="language-lang">...</code></pre> for Telegram
    def replace_code_block(match: re.Match) -> str:
        lang = match.group(1).strip()
        code = match.group(2)
        if lang:
            return f'<pre><code class="language-{lang}">{code}</code></pre>'
        return f"<pre>{code}</pre>"

    text = re.sub(r"```(.*?)\n(.*?)\n```", replace_code_block, text, flags=re.DOTALL)
    text = re.sub(r"```(.*?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)

    # Replace tables
    table_pattern = re.compile(r"(?:^.*\|.*(?:\n|$))+", re.MULTILINE)

    def replace_table(match: re.Match) -> str:
        table_content = str(match.group(0)).strip()
        # Verify it has a separator line (e.g., |---| or ---|---)
        if re.search(
            r"^[ \t]*\|?[\s\-:]*[-]+[\s\-:]*\|[\s\-:|]*$", table_content, re.MULTILINE
        ):
            return f"\n<pre>{table_content}</pre>\n\n"
        return str(match.group(0))

    text = table_pattern.sub(replace_table, text)

    # Replace inline code: `code`
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # Replace headers: # Header or ## Header -> <b>Header</b>
    text = re.sub(r"^[ \t]*#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Replace blockquotes: > quote (escaped to &gt; by html.escape)
    text = re.sub(
        r"^[ \t]*&gt;\s+(.+)$", r"<blockquote>\1</blockquote>", text, flags=re.MULTILINE
    )

    # Replace unordered lists: - item or * item -> • item
    # Also preserve the leading indentation
    text = re.sub(r"^([ \t]*)[\*\-]\s+(.+)$", r"\1• \2", text, flags=re.MULTILINE)

    # Replace bold: **bold** or __bold__
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", text)

    # Replace italic: *italic* or _italic_
    # Be careful not to match inside words like snake_case, and don't cross newlines
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^\_\n]+)_(?!\w)", r"<i>\1</i>", text)

    # Replace strikethrough: ~~strike~~
    text = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", text)

    # Replace links: [text](url)
    text = re.sub(r"\[([^\]\n]+)\]\(([^)\n]+)\)", r'<a href="\2">\1</a>', text)

    return text
