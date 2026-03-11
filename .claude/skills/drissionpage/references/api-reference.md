# DrissionPage API Reference

## Table of Contents
- [Browser Initialization](#browser-initialization)
- [Page Navigation](#page-navigation)
- [Element Locating Syntax](#element-locating-syntax)
- [Element Interaction](#element-interaction)
- [Wait Methods](#wait-methods)
- [Element Properties](#element-properties)
- [Multi-Tab Operations](#multi-tab-operations)
- [Settings](#settings)

---

## Browser Initialization

```python
from DrissionPage import Chromium

browser = Chromium()
tab = browser.latest_tab
```

**With options:**
```python
from DrissionPage import Chromium, ChromiumOptions

co = ChromiumOptions()
co.headless()                          # Headless mode
co.set_argument('--no-sandbox')        # Add browser argument
co.set_user_agent('custom-ua')         # Custom User-Agent
co.set_proxy('http://127.0.0.1:8080')  # Set proxy

browser = Chromium(co)
```

---

## Page Navigation

```python
tab.get('https://example.com')
tab.get('https://example.com', retry=3, interval=2, timeout=30)

tab.back()      # Go back
tab.forward()   # Go forward
tab.refresh()   # Refresh page
```

---

## Element Locating Syntax

### Single Element: `ele()`
### Multiple Elements: `eles()`

| Syntax | Description | Example |
|--------|-------------|---------|
| `#id` | ID selector | `tab.ele('#username')` |
| `.class` | Class selector | `tab.ele('.btn-primary')` |
| `@attr=value` | Attribute selector | `tab.ele('@name=email')` |
| `@attr:value` | Attribute contains | `tab.ele('@class:active')` |
| `@attr^value` | Attribute starts with | `tab.ele('@id^user')` |
| `@attr$value` | Attribute ends with | `tab.ele('@id$name')` |
| `tag:name` | Tag name | `tab.ele('tag:div')` |
| `text=xxx` | Exact text match | `tab.ele('text=Login')` |
| `text:xxx` | Text contains | `tab.ele('text:Submit')` |
| `xxx` | Text contains (shorthand) | `tab.ele('Submit')` |
| `css:selector` | CSS selector | `tab.ele('css:#div1>span')` |
| `xpath:path` | XPath | `tab.ele('xpath://div[@id="main"]')` |

### Match Modifiers

| Modifier | Meaning | Example |
|----------|---------|---------|
| `=` | Exact match | `#=one` |
| `:` | Contains | `#:ne` |
| `^` | Starts with | `#^on` |
| `$` | Ends with | `#$ne` |

### Combined Conditions

```python
# Multiple attributes
tab.ele('@tag()=input@@type=text@@name=user')

# Relative locating
ele.parent()                    # Parent element
ele.next()                      # Next sibling
ele.prev()                      # Previous sibling
ele.child('tag:div')            # Child element
ele.children()                  # All children
ele.ele('css:>div')             # Direct child via CSS
```

### Chain Locating (Shorthand)

```python
# Equivalent to tab.ele().ele().ele()
tab('#container')('.item')('text:Click')
```

---

## Element Interaction

### Click

```python
ele.click()                     # Normal click
ele.click(by_js=True)           # JavaScript click
ele.click.left()                # Left click
ele.click.right()               # Right click
ele.click.middle()              # Middle click
ele.click.at(x=10, y=20)        # Click at offset
ele.click.twice()               # Double click
```

### Input

```python
ele.input('text')               # Input text
ele.input('text', clear=True)   # Clear first, then input
ele.input('text', by_js=True)   # Input via JavaScript

# Keyboard shortcuts
from DrissionPage.common import Keys
ele.input((Keys.CTRL, 'a'))     # Ctrl+A
ele.input(Keys.ENTER)           # Enter key
ele.input('text\n')             # Input + Enter
```

### Clear

```python
ele.clear()                     # Clear via keyboard
ele.clear(by_js=True)           # Clear via JavaScript
```

### Other Actions

```python
ele.focus()                     # Focus element
ele.hover()                     # Hover over element
ele.drag_to(target_ele)         # Drag to another element
ele.scroll.to_see()             # Scroll element into view
```

---

## Wait Methods

### Page-level Wait

```python
tab.wait.load_start()                      # Wait for page load start
tab.wait.load_complete()                   # Wait for page load complete
tab.wait.ele_displayed('#div1')            # Wait for element visible
tab.wait.ele_displayed('#div1', timeout=5) # With timeout
tab.wait.eles_loaded('#div1')              # Wait for element in DOM
tab.wait.ele_deleted('#loading')           # Wait for element removed
tab.wait(2)                                # Wait fixed seconds
```

### Element-level Wait

```python
ele.wait.displayed()            # Wait until visible
ele.wait.displayed(timeout=3)   # With timeout
ele.wait.hidden()               # Wait until hidden
ele.wait.deleted()              # Wait until removed from DOM
ele.wait.enabled()              # Wait until enabled
ele.wait.disabled()             # Wait until disabled
ele.wait.covered()              # Wait until covered
ele.wait.not_covered()          # Wait until not covered
ele.wait.has_rect()             # Wait until has dimensions
```

---

## Element Properties

```python
ele.text                        # Text content
ele.inner_html                  # Inner HTML
ele.html                        # Outer HTML
ele.tag                         # Tag name
ele.attr('href')                # Get attribute
ele.attrs                       # All attributes dict
ele.style('color')              # Get CSS style
ele.rect.location               # Element location (x, y)
ele.rect.size                   # Element size (width, height)
ele.states.is_displayed         # Is visible
ele.states.is_enabled           # Is enabled
ele.states.is_checked           # Is checked (checkbox/radio)
ele.states.is_selected          # Is selected (option)
ele.states.is_covered           # Is covered by other element
```

---

## Multi-Tab Operations

```python
# Get tabs
tab1 = browser.latest_tab
tab2 = browser.new_tab()
tab3 = browser.get_tab(index=0)
tabs = browser.tabs

# Tab operations
tab.set.activate()              # Activate tab
tab.close()                     # Close tab

# Simultaneous operation
tab1.get('https://site1.com')
tab2.get('https://site2.com')
```

---

## Settings

### Global Settings

```python
from DrissionPage.common import Settings

Settings.set_raise_when_wait_failed(True)   # Raise exception on wait timeout
Settings.set_browser_connect_timeout(45.0)  # Browser connection timeout
```

### Page Settings

```python
tab.set.timeouts(page_load=30, script=10)   # Set timeouts
tab.set.window.max()                         # Maximize window
tab.set.window.size(1920, 1080)             # Set window size
tab.set.window.hide()                        # Hide browser
tab.set.window.show()                        # Show browser
tab.set.cookies(cookies_list)                # Set cookies
tab.set.headers({'X-Custom': 'value'})       # Set headers
tab.set.user_agent('custom-ua')              # Set User-Agent
```

### Load Strategy

```python
tab.set.load_strategy.normal()   # Wait for full load (default)
tab.set.load_strategy.eager()    # Wait for DOM ready
tab.set.load_strategy.none()     # Don't wait
```

---

## iframe Handling

DrissionPage handles iframes transparently - no manual switching required:

```python
# Directly locate element inside iframe
ele = tab.ele('#element-in-iframe')

# Or get iframe object explicitly
frame = tab.get_frame('#iframe-id')
ele = frame.ele('#element')
```
