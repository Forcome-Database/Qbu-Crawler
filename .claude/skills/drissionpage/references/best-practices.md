# DrissionPage Best Practices

## Table of Contents
- [Element Locating Strategies](#element-locating-strategies)
- [Wait Strategies](#wait-strategies)
- [Error Handling](#error-handling)
- [Performance Optimization](#performance-optimization)
- [Common Patterns](#common-patterns)
- [Debugging Tips](#debugging-tips)

---

## Element Locating Strategies

### Priority Order (Most to Least Reliable)

1. **ID** - Most stable, use when available
   ```python
   tab.ele('#unique-id')
   ```

2. **data-* attributes** - Designed for testing, rarely change
   ```python
   tab.ele('@data-testid=submit-btn')
   ```

3. **name attribute** - Good for form elements
   ```python
   tab.ele('@name=username')
   ```

4. **CSS selector** - Flexible, good for complex structures
   ```python
   tab.ele('css:.form-group input[type="email"]')
   ```

5. **Text content** - Use for buttons/links, may break with i18n
   ```python
   tab.ele('text=Submit')
   ```

6. **XPath** - Last resort, fragile to DOM changes
   ```python
   tab.ele('xpath://div[@class="container"]//button')
   ```

### Avoid Fragile Locators

```python
# Bad - position-dependent
tab.ele('xpath:/html/body/div[3]/div[2]/button')

# Bad - auto-generated class names
tab.ele('.css-1a2b3c4')

# Good - semantic locator
tab.ele('@data-testid=checkout-btn')
tab.ele('#checkout-button')
```

### Centralize Selectors

Keep selectors in a dedicated class for maintainability:

```python
class PageSelectors:
    LOGIN_USERNAME = '#username'
    LOGIN_PASSWORD = '#password'
    LOGIN_SUBMIT = '@data-testid=login-submit'

# Usage
tab.ele(PageSelectors.LOGIN_USERNAME).input('user')
```

---

## Wait Strategies

### Explicit Waits (Recommended)

```python
# Wait for specific element
tab.wait.ele_displayed('#content', timeout=10)

# Wait for element to disappear (loading spinner)
tab.wait.ele_deleted('.loading-spinner', timeout=30)

# Element-level wait
ele = tab.ele('#button')
ele.wait.enabled(timeout=5)
ele.click()
```

### Avoid Fixed Waits

```python
# Bad - wastes time or may not be enough
import time
time.sleep(3)
tab.ele('#content').click()

# Good - waits only as long as needed
tab.wait.ele_displayed('#content')
tab.ele('#content').click()
```

### Wait for Page State

```python
# Wait for page load complete
tab.wait.load_complete()

# Wait for AJAX to finish (check for loading indicator)
tab.wait.ele_deleted('.ajax-loading')

# Wait for specific content to appear
tab.wait.ele_displayed('text:Data loaded')
```

---

## Error Handling

### Check Element Existence

```python
# Method 1: Check if element exists
ele = tab.ele('#optional-element', timeout=2)
if ele:
    ele.click()

# Method 2: Use try-except for critical operations
try:
    tab.ele('#required-element', timeout=5).click()
except Exception as e:
    logger.error(f"Element not found: {e}")
    # Handle error or retry
```

### Retry Pattern

```python
def click_with_retry(tab, selector, max_retries=3):
    for attempt in range(max_retries):
        try:
            ele = tab.ele(selector, timeout=5)
            if ele:
                ele.click()
                return True
        except Exception:
            if attempt < max_retries - 1:
                tab.refresh()
                tab.wait.load_complete()
    return False
```

### Global Exception Settings

```python
from DrissionPage.common import Settings

# Raise exception when wait fails (useful for debugging)
Settings.set_raise_when_wait_failed(True)
```

---

## Performance Optimization

### Set Appropriate Timeouts

```python
# Global timeout settings
tab.set.timeouts(page_load=30, script=10)

# Per-operation timeout
ele = tab.ele('#element', timeout=3)  # Short timeout for known fast elements
```

### Use Load Strategy

```python
# Don't wait for full page load if not needed
tab.set.load_strategy.eager()  # DOM ready is enough
tab.set.load_strategy.none()   # Don't wait at all

# Navigate
tab.get('https://example.com')
tab.wait.ele_displayed('#main-content')  # Wait for what you need
```

### Batch Operations

```python
# Bad - multiple round trips
for item in items:
    tab.ele(f'#item-{item}').click()
    tab.wait(0.5)

# Good - use JavaScript for batch operations
tab.run_js('''
    document.querySelectorAll('.item').forEach(el => el.click());
''')
```

### Reuse Browser Instance

```python
# Bad - creates new browser each time
def process_page(url):
    browser = Chromium()
    tab = browser.latest_tab
    tab.get(url)
    # ...
    browser.quit()

# Good - reuse browser
browser = Chromium()
tab = browser.latest_tab

def process_page(url):
    tab.get(url)
    # ...

# Quit when all done
browser.quit()
```

---

## Common Patterns

### Login Flow

```python
def login(tab, username, password):
    tab.get('https://example.com/login')
    tab.wait.ele_displayed('#username')

    tab.ele('#username').input(username, clear=True)
    tab.ele('#password').input(password, clear=True)
    tab.ele('#login-btn').click()

    # Wait for login success indicator
    tab.wait.ele_displayed('.user-profile', timeout=10)
```

### Form Submission

```python
def fill_form(tab, data):
    # Text inputs
    tab.ele('#name').input(data['name'], clear=True)
    tab.ele('#email').input(data['email'], clear=True)

    # Dropdown
    tab.ele('#country').click()
    tab.ele(f'text={data["country"]}').click()

    # Checkbox
    checkbox = tab.ele('#agree-terms')
    if not checkbox.states.is_checked:
        checkbox.click()

    # Submit
    tab.ele('#submit').click()
    tab.wait.ele_displayed('.success-message')
```

### Table Data Extraction

```python
def extract_table_data(tab, table_selector):
    rows = tab.eles(f'{table_selector} tr')
    data = []

    for row in rows[1:]:  # Skip header
        cells = row.eles('tag:td')
        data.append({
            'col1': cells[0].text,
            'col2': cells[1].text,
            'col3': cells[2].text,
        })

    return data
```

### Pagination Handling

```python
def process_all_pages(tab):
    all_data = []

    while True:
        # Process current page
        items = tab.eles('.item')
        for item in items:
            all_data.append(item.text)

        # Check for next page
        next_btn = tab.ele('.next-page', timeout=2)
        if not next_btn or 'disabled' in next_btn.attr('class'):
            break

        next_btn.click()
        tab.wait.load_complete()

    return all_data
```

### Screenshot on Error

```python
def safe_operation(tab, operation_func):
    try:
        return operation_func(tab)
    except Exception as e:
        # Save screenshot for debugging
        tab.get_screenshot(path='error_screenshot.png')
        raise
```

---

## Debugging Tips

### Enable Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Inspect Element State

```python
ele = tab.ele('#element')
print(f"Text: {ele.text}")
print(f"HTML: {ele.html}")
print(f"Attributes: {ele.attrs}")
print(f"Is displayed: {ele.states.is_displayed}")
print(f"Is enabled: {ele.states.is_enabled}")
print(f"Location: {ele.rect.location}")
print(f"Size: {ele.rect.size}")
```

### Take Screenshots

```python
# Full page screenshot
tab.get_screenshot(path='debug.png', full_page=True)

# Element screenshot
ele.get_screenshot(path='element.png')
```

### Execute JavaScript for Debugging

```python
# Check page state
result = tab.run_js('return document.readyState')
print(f"Page state: {result}")

# Get computed styles
styles = tab.run_js('''
    const el = document.querySelector('#element');
    return window.getComputedStyle(el).display;
''')
```

### Pause for Manual Inspection

```python
# During development, pause to inspect browser
input("Press Enter to continue...")
```
