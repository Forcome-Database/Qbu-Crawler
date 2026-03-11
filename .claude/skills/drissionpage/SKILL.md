---
name: DrissionPage
description: |
  Python browser automation with DrissionPage library. Use when:
  (1) Writing browser automation scripts (login, form filling, scraping)
  (2) Locating web elements (by ID, class, text, CSS, XPath)
  (3) Interacting with pages (click, input, wait, scroll)
  (4) Questions about DrissionPage API or best practices
  (5) Debugging DrissionPage code or element locating issues
---

# DrissionPage Browser Automation

DrissionPage is a Python browser automation library combining browser control with requests efficiency.

## Quick Start

```python
from DrissionPage import Chromium

browser = Chromium()
tab = browser.latest_tab
tab.get('https://example.com')

# Locate and interact
tab.ele('#username').input('user')
tab.ele('#password').input('pass')
tab.ele('#login-btn').click()

# Wait for result
tab.wait.ele_displayed('.welcome-message')
```

## Element Locating Syntax

| Syntax | Example |
|--------|---------|
| `#id` | `tab.ele('#username')` |
| `.class` | `tab.ele('.btn-primary')` |
| `@attr=value` | `tab.ele('@name=email')` |
| `text=xxx` | `tab.ele('text=Login')` |
| `text:xxx` | `tab.ele('text:Submit')` |
| `css:selector` | `tab.ele('css:#form input')` |
| `xpath:path` | `tab.ele('xpath://div[@id="main"]')` |

**Modifiers:** `=` exact, `:` contains, `^` starts with, `$` ends with

## Core Operations

```python
# Input
ele.input('text')
ele.input('text', clear=True)

# Click
ele.click()
ele.click(by_js=True)

# Wait
tab.wait.ele_displayed('#element', timeout=10)
tab.wait.ele_deleted('.loading')
ele.wait.enabled()

# Properties
ele.text
ele.attr('href')
ele.states.is_displayed
```

## References

- **Full API reference**: See [references/api-reference.md](references/api-reference.md) for complete element locating syntax, interaction methods, wait methods, and settings
- **Best practices**: See [references/best-practices.md](references/best-practices.md) for locating strategies, error handling, performance tips, and common patterns
