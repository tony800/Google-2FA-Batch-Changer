"""
@file change_2fa_service.py
@brief 批量更改2FA密钥服务
@details 自动化更改Google账号的Authenticator 2FA密钥
"""
import asyncio
import re
from typing import Tuple, Optional, Dict, Any, List, Callable

import pyotp
from playwright.async_api import Page, BrowserContext, expect

from .google_auth import google_login, _extract_logged_in_email


def print(*args, **kwargs):
    """Do not emit raw automation output containing authentication material."""


# ==================== 常量配置 ====================
TWO_FACTOR_URL = "https://myaccount.google.com/two-step-verification/authenticator?utm_source=google-account&utm_medium=web&utm_campaign=authenticator-screen"
DEFAULT_TIMEOUT = 30000  # 30秒
SMART_WAIT_TIMEOUT = 15000  # 智能等待超时 15秒


async def _confirm_target_account(
    page: Page,
    email: str,
    log: Callable = None,
    attempts: int = 8,
) -> bool:
    """
    @brief 双重验证当前登录账号：头像 aria-label 优先，页面源码容错。
    @details 设置页的头像可能晚于 networkidle 渲染，因此轮询重试；
             页面源码中出现目标邮箱字符串同样视为确认。
    """
    target = email.strip().lower()
    for attempt in range(attempts):
        extracted = await _extract_logged_in_email(page)
        if extracted:
            if extracted.strip().lower() == target:
                return True
            return False  # 确认登录的是另一个账号，绝不继续
        try:
            if target in (await page.content()).lower():
                return True
        except Exception:
            pass
        if attempt < attempts - 1:
            await asyncio.sleep(2)
    return False


class Change2FAStatus:
    """2FA更改状态"""
    SUCCESS = 'success'
    FAILED = 'failed'
    LOGIN_FAILED = 'login_failed'
    VERIFICATION_FAILED = 'verification_failed'
    KEY_EXTRACTION_FAILED = 'key_extraction_failed'
    ERROR = 'error'


async def change_2fa_for_account(
    page: Page,
    account_info: dict,
    log_callback: Optional[Callable[[str], None]] = None,
    key_prepared_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    @brief 为单个账号更改2FA密钥
    @param page Playwright页面对象
    @param account_info 账号信息字典 {email, password, twofa_key, recovery_email}
    @param log_callback 日志回调函数
    @return (success, message, new_2fa_key)
    """
    email = account_info.get('email', 'Unknown')
    old_2fa_key = account_info.get('twofa_key', '')
    
    def log(msg: str):
        full_msg = f"[Change2FA] [{email}] {msg}"
        print(full_msg)
        if log_callback:
            log_callback(full_msg)
    
    try:
        # ==================== Step 1: 登录 ====================
        log("Step 1: 开始登录...")
        login_success, login_msg, login_2fa_code = await google_login(page, account_info, log)
        
        if not login_success:
            log(f"❌ 登录失败: {login_msg}")
            return False, f"登录失败: {login_msg}", None
        
        log(f"✅ 登录成功 (login_2fa_code={'set' if login_2fa_code else 'none'})")
        
        # ==================== Step 2: 导航到2FA设置页面 ====================
        log("Step 2: 导航到2FA设置页面...")
        await page.goto(TWO_FACTOR_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        # 智能等待页面稳定
        await page.wait_for_load_state("networkidle", timeout=15000)

        if not await _confirm_target_account(page, email, log):
            return False, "无法确认当前登录账号与目标账号一致，请人工核对", None
        
        # ==================== Step 3: 验证身份（可能需要密码和/或2FA） ====================
        log("Step 3: 检测是否需要验证身份...")
        
        # 首先检查是否需要输入密码
        need_password = await _check_need_password(page, log)
        if need_password:
            password = account_info.get('password', '')
            if not password:
                log("❌ 需要密码验证但账号无密码")
                return False, "需要密码验证但账号无密码", None
            
            log("检测到需要输入密码...")
            pwd_success = await _input_password(page, password, log)
            if pwd_success:
                log("✅ 密码输入完成")
                # 等待页面跳转
                await page.wait_for_load_state("networkidle", timeout=10000)
            else:
                log("❌ 密码输入失败")
                return False, "密码输入失败", None
        
        # 再检测是否需要2FA验证（密码输入后可能还需要2FA）
        need_2fa_verification = await _check_need_2fa_verification(page, log)
        
        if need_2fa_verification:
            if not old_2fa_key:
                log("❌ 需要2FA验证但无2FA密钥")
                return False, "需要2FA验证但账号无2FA密钥", None
            
            log("输入当前2FA验证码...")
            # 传入登录时使用的验证码，防止在同一30秒窗口内重复使用被Google拒绝
            verify_success = await _input_current_2fa(page, old_2fa_key, log, last_used_code=login_2fa_code)
            if verify_success:
                log("✅ 2FA验证通过")
                # 等待页面跳转
                await page.wait_for_load_state("networkidle", timeout=10000)
            else:
                log("⚠️ 2FA验证可能未完成")
        else:
            log("无需2FA验证，继续下一步")

        if not await _confirm_target_account(page, email, log):
            return False, "无法确认当前登录账号与目标账号一致，请人工核对", None
        
        # ==================== Step 4: 点击 "Change authenticator app" ====================
        log("Step 4: 点击 'Change authenticator app'...")
        
        change_btn_success = await _click_change_authenticator_button(page, log)
        if not change_btn_success:
            log("❌ 找不到 'Change authenticator app' 按钮")
            return False, "找不到更改按钮", None
        
        log("✅ 已点击更改按钮")
        
        # ==================== Step 5: 点击 "Can't scan it?" ====================
        log("Step 5: 点击 'Can't scan it?'...")
        
        cant_scan_success = await _click_cant_scan_button(page, log)
        if not cant_scan_success:
            log("❌ 找不到 'Can't scan it?' 按钮")
            return False, "找不到'Can't scan it?'按钮", None
        
        log("✅ 已点击 'Can't scan it?'")
        
        # ==================== Step 6: 提取新的2FA密钥 ====================
        log("Step 6: 提取新的2FA密钥...")
        
        new_2fa_key = await _extract_new_2fa_key(page, log)
        if not new_2fa_key:
            log("❌ 无法提取2FA密钥")
            return False, "无法提取新的2FA密钥", None
        
        log(f"✅ 提取到新密钥: {new_2fa_key[:8]}...")

        if key_prepared_callback is None:
            return False, "缺少安全保存回调，拒绝提交密钥更改", None
        key_prepared_callback(new_2fa_key)
        
        # ==================== Step 7: 点击 "Next" ====================
        log("Step 7: 点击 'Next'...")
        
        next_success = await _click_next_button(page, log)
        if not next_success:
            log("❌ 找不到 'Next' 按钮")
            return False, "找不到Next按钮", None
        
        log("✅ 已点击 'Next'")
        
        # ==================== Step 8 & 9: 输入验证码并验证（带重试） ====================
        log("Step 8: 输入新密钥的验证码并验证...")
        
        max_verify_retries = 5
        
        for verify_attempt in range(max_verify_retries):
            if verify_attempt > 0:
                log(f"🔄 第 {verify_attempt + 1}/{max_verify_retries} 次重试...")
            
            # Step 8: 输入验证码（每次直接使用当前验证码，不等待）
            verify_new_success, used_code = await _verify_new_2fa(page, new_2fa_key, log)
            if not verify_new_success:
                log("❌ 无法输入验证码")
                return False, "新密钥验证失败", None
            
            log(f"✅ 已输入验证码: {used_code}")
            
            # Step 9: 点击 Verify 并检测结果
            log("Step 9: 点击 'Verify' 完成更改...")
            verify_result, need_retry = await _click_verify_button(page, new_2fa_key, log)
            
            if verify_result:
                log("🎉 2FA密钥更改成功!")
                return True, "2FA密钥更改成功", new_2fa_key
            
            if need_retry and verify_attempt < max_verify_retries - 1:
                log(f"⚠️ 验证码错误，2秒后重试...")
                await asyncio.sleep(2)
                continue
            else:
                log("❌ 最终验证失败")
                return False, "最终验证失败", None
        
        log("❌ 验证重试次数用尽")
        return False, "验证重试次数用尽", None
        
    except Exception as e:
        error_msg = f"更改2FA异常: {str(e)}"
        log(f"❌ {error_msg}")
        return False, error_msg, None


async def _check_need_password(page: Page, log: Callable = None) -> bool:
    """
    @brief 检测是否需要输入密码
    @details 检测 Google 账号密码验证页面
    """
    def _log(msg):
        if log:
            log(msg)
        print(f"[Change2FA] {msg}")
    
    try:
        # 等待页面稳定
        await page.wait_for_load_state("networkidle", timeout=10000)
        
        current_url = page.url
        _log(f"当前页面URL: {current_url[:80]}...")
        
        # 检查是否在密码输入页面
        # URL 特征
        if 'signin/challenge/pwd' in current_url or 'signin/v2/challenge/pwd' in current_url:
            _log("URL 显示为密码验证页面")
            return True
        
        # 页面元素特征
        pwd_input = page.locator('input[type="password"]')
        pwd_label_1 = page.locator('text=/enter.*password/i')
        pwd_label_2 = page.locator('text=输入密码')
        pwd_label_3 = page.locator('label:has-text("Enter your password")')
        
        combined = pwd_input.or_(pwd_label_1).or_(pwd_label_2).or_(pwd_label_3)
        
        try:
            # 短时间检测
            await expect(combined.first).to_be_visible(timeout=5000)
            _log("检测到密码输入页面")
            return True
        except:
            _log("未检测到密码输入页面")
            return False
            
    except Exception as e:
        if log:
            log(f"检测密码页面异常: {e}")
        return False


async def _input_password(page: Page, password: str, log: Callable = None) -> bool:
    """
    @brief 输入密码
    @param page Playwright页面对象
    @param password 密码
    @param log 日志回调
    @return 是否成功
    """
    def _log(msg):
        if log:
            log(msg)
        print(f"[Change2FA] {msg}")
    
    try:
        # 定位密码输入框（排除隐藏 honeypot 字段）
        pwd_input = page.locator(
            'input[name="Passwd"], input[type="password"]:not([name="hiddenPassword"])'
        )
        
        # 等待输入框可见
        try:
            await expect(pwd_input.first).to_be_visible(timeout=10000)
            _log("找到密码输入框")
        except:
            _log("未找到密码输入框")
            return False
        
        # 清空并输入密码
        await pwd_input.first.fill('')
        await pwd_input.first.fill(password)
        _log("已输入密码")
        
        # 查找并点击下一步按钮
        btn_next = page.locator('button:has-text("Next")')
        btn_submit = page.locator('button[type="submit"]')
        btn_signin = page.locator('button:has-text("Sign in")')
        btn_login = page.locator('button:has-text("登录")')
        btn_next_cn = page.locator('button:has-text("下一步")')
        
        combined_btn = btn_next.or_(btn_submit).or_(btn_signin).or_(btn_login).or_(btn_next_cn)
        
        try:
            await expect(combined_btn.first).to_be_visible(timeout=5000)
            await combined_btn.first.click(force=True)
            _log("已点击下一步按钮")
        except:
            _log("未找到下一步按钮，尝试按回车")
            await pwd_input.first.press("Enter")
        
        # 等待页面响应
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        # 检查是否有错误提示
        await asyncio.sleep(1)
        error_msg = page.locator('text=/wrong.*password/i, text=/incorrect.*password/i, text=密码错误')
        try:
            if await error_msg.count() > 0 and await error_msg.first.is_visible():
                _log("❌ 密码错误")
                return False
        except:
            pass
        
        _log("✅ 密码验证完成")
        return True
        
    except Exception as e:
        _log(f"输入密码异常: {e}")
        return False


async def _check_need_2fa_verification(page: Page, log: Callable = None) -> bool:
    """
    @brief 使用智能等待检测是否需要输入2FA验证码
    @details 使用 .or_() 组合多个定位器并行检测
    """
    def _log(msg):
        if log:
            log(msg)
        print(f"[Change2FA] {msg}")
    
    try:
        # 等待页面稳定
        await page.wait_for_load_state("networkidle", timeout=10000)
        
        # 检查页面 URL 和内容
        current_url = page.url
        _log(f"当前页面URL: {current_url[:80]}...")
        
        # 组合多种2FA验证页面特征
        # Google 2FA 验证页面的输入框
        code_input_1 = page.locator('input[type="tel"]')
        code_input_2 = page.locator('input[id="totpPin"]')
        code_input_3 = page.locator('input[autocomplete="one-time-code"]')
        code_input_4 = page.locator('input[name="totpPin"]')
        # 验证码输入框的通用特征
        code_input_5 = page.locator('input[aria-label*="code" i]')
        code_input_6 = page.locator('input[aria-label*="验证" i]')
        # 验证提示文本
        verify_text_1 = page.locator('text=/enter.*code/i')
        verify_text_2 = page.locator('text=/verify.*identity/i')
        verify_text_3 = page.locator('text=2-Step Verification')
        verify_text_4 = page.locator('text=两步验证')
        
        # 使用 .or_() 组合所有定位器
        combined = (
            code_input_1
            .or_(code_input_2)
            .or_(code_input_3)
            .or_(code_input_4)
            .or_(code_input_5)
            .or_(code_input_6)
            .or_(verify_text_1)
            .or_(verify_text_2)
            .or_(verify_text_3)
            .or_(verify_text_4)
        )
        
        # 智能等待：检测2FA验证页面
        try:
            await expect(combined.first).to_be_visible(timeout=SMART_WAIT_TIMEOUT)
            _log("检测到2FA验证页面")
            return True
        except:
            # 再检查一下是否已经在 Change authenticator 页面
            change_btn = page.locator('button:has-text("Change authenticator"), span:has-text("Change authenticator")')
            try:
                if await change_btn.count() > 0:
                    _log("已在 Change authenticator 页面，无需2FA验证")
                    return False
            except:
                pass
            
            _log("未检测到2FA验证页面")
            return False
    except Exception as e:
        if log:
            log(f"检测2FA验证页面异常: {e}")
        return False


async def _input_current_2fa(page: Page, twofa_key: str, log: Callable, last_used_code: str = None) -> bool:
    """
    @brief 输入当前的2FA验证码
    @param last_used_code 上次使用过的验证码，如果当前验证码相同则等待新验证码
    """
    totp = pyotp.TOTP(twofa_key.replace(' ', ''))
    
    # 组合所有可能的输入框定位器
    input_tel = page.locator('input[type="tel"]')
    input_otp = page.locator('input[autocomplete="one-time-code"]')
    input_totp = page.locator('#totpPin')
    input_totp_name = page.locator('input[name="totpPin"]')
    input_code = page.locator('input[placeholder*="code" i]')
    input_aria = page.locator('input[aria-label*="code" i]')
    input_text = page.locator('input[type="text"]:not([name="email"])')
    
    combined_input = (
        input_tel
        .or_(input_otp)
        .or_(input_totp)
        .or_(input_totp_name)
        .or_(input_code)
        .or_(input_aria)
    )
    
    # 组合所有可能的下一步按钮
    btn_next = page.locator('button:has-text("Next")')
    btn_verify = page.locator('button:has-text("Verify")')
    btn_submit = page.locator('button[type="submit"]')
    btn_next_id = page.locator('#totpNext >> button')
    btn_continue = page.locator('button:has-text("Continue")')
    btn_done = page.locator('button:has-text("Done")')
    
    combined_btn = (
        btn_next
        .or_(btn_verify)
        .or_(btn_submit)
        .or_(btn_next_id)
        .or_(btn_continue)
        .or_(btn_done)
    )
    
    try:
        # 计算当前验证码
        code = totp.now()
        
        # 只有当明确传入了上次使用的验证码，且当前码与其相同时才等待
        # 不传入 last_used_code 时直接使用当前验证码，提高效率
        if last_used_code is not None and code == last_used_code:
            log(f"验证码 {code} 与上次使用的相同，等待新验证码...")
            # 最多等待35秒（确保跨过一个周期），每5秒检查一次
            for attempt in range(7):
                await asyncio.sleep(5)
                new_code = totp.now()
                if new_code != last_used_code:
                    code = new_code
                    log(f"✅ 获取到新验证码: {code}")
                    break
            else:
                log("⚠️ 等待新验证码超时（35秒），将使用当前验证码")
                code = totp.now()
        
        log(f"使用2FA验证码: {code}")
        
        # 智能等待输入框出现
        try:
            await expect(combined_input.first).to_be_visible(timeout=SMART_WAIT_TIMEOUT)
            log("找到2FA输入框")
        except:
            # 尝试更宽泛的选择
            try:
                await expect(input_text.first).to_be_visible(timeout=5000)
                combined_input = input_text
                log("使用备用输入框定位")
            except:
                log("未找到2FA输入框")
                return False
        
        # 清空并填入验证码
        await combined_input.first.fill('')
        await combined_input.first.fill(code)
        log(f"已填入验证码: {code}")
        
        # 智能等待按钮并点击
        try:
            await expect(combined_btn.first).to_be_visible(timeout=5000)
            await combined_btn.first.click(force=True)
            log("已点击下一步按钮")
        except:
            log("未找到下一步按钮，尝试按回车")
            await combined_input.first.press("Enter")
        
        # 等待页面响应
        await page.wait_for_load_state("networkidle", timeout=10000)
        return True
        
    except Exception as e:
        log(f"输入2FA验证码异常: {e}")
        return False


async def _click_change_authenticator_button(page: Page, log: Callable) -> bool:
    """
    @brief 智能等待并点击 'Change authenticator app' 按钮
    """
    try:
        # 组合多种定位方式
        btn_text = page.locator('button:has-text("Change authenticator app")')
        span_text = page.locator('span:has-text("Change authenticator app")')
        btn_jsname = page.locator('[jsname="V67aGc"]:has-text("Change authenticator app")')
        btn_role = page.get_by_role("button", name=re.compile(r"Change.*authenticator", re.IGNORECASE))
        
        combined = btn_text.or_(span_text).or_(btn_jsname).or_(btn_role)
        
        # 步骤1：智能等待按钮出现（30秒）
        try:
            await expect(combined.first).to_be_visible(timeout=30000)
            log("找到 'Change authenticator app' 按钮")
        except Exception as e:
            log(f"等待按钮出现超时: {e}")
            return False
        
        # 步骤2：点击按钮（单独 try，不让等待页面加载影响结果）
        try:
            await combined.first.click(force=True)
            log("✅ 已点击 'Change authenticator app' 按钮")
        except Exception as e:
            log(f"点击按钮失败: {e}")
            return False
        
        # 步骤3：等待页面变化（超时不影响结果）
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except:
            pass
        
        return True
            
    except Exception as e:
        log(f"点击更改按钮异常: {e}")
        return False


async def _click_cant_scan_button(page: Page, log: Callable) -> bool:
    """
    @brief 智能等待并点击 'Can't scan it?' 按钮
    """
    try:
        # 组合多种定位方式
        btn_text = page.locator('button:has-text("Can\'t scan it?")')
        span_text = page.locator('span:has-text("Can\'t scan it?")')
        btn_jsname = page.locator('[jsname="V67aGc"]:has-text("scan")')
        btn_role = page.get_by_role("button", name=re.compile(r"Can.*scan", re.IGNORECASE))
        
        combined = btn_text.or_(span_text).or_(btn_jsname).or_(btn_role)
        
        # 步骤1：智能等待按钮出现（30秒）
        try:
            await expect(combined.first).to_be_visible(timeout=30000)
            log("找到 'Can't scan it?' 按钮")
        except Exception as e:
            log(f"等待按钮出现超时: {e}")
            return False
        
        # 步骤2：点击按钮
        try:
            await combined.first.click(force=True)
            log("✅ 已点击 'Can't scan it?' 按钮")
        except Exception as e:
            log(f"点击按钮失败: {e}")
            return False
        
        # 步骤3：等待页面变化（超时不影响结果）
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except:
            pass
        
        return True
    except Exception as e:
        log(f"点击'Can't scan'按钮异常: {e}")
        return False


async def _extract_new_2fa_key(page: Page, log: Callable) -> Optional[str]:
    """
    @brief 使用智能等待提取新的2FA密钥
    """
    try:
        # 智能等待包含密钥的页面元素出现
        key_container = page.locator('[wizard-step-uid*="manualKey"], ol.AOmWL, div:has(strong)')
        try:
            await expect(key_container.first).to_be_visible(timeout=SMART_WAIT_TIMEOUT)
        except:
            log("等待密钥容器超时，尝试直接提取")
        
        # 方法1: 从 <strong> 标签提取
        try:
            strong_elements = page.locator('strong')
            count = await strong_elements.count()
            
            for i in range(count):
                text = await strong_elements.nth(i).text_content()
                if text:
                    # 去掉空格，检查是否是32位字母数字
                    cleaned = text.replace(' ', '').strip().upper()
                    if len(cleaned) == 32 and cleaned.isalnum():
                        log(f"从<strong>提取到密钥")
                        return cleaned
        except:
            pass
        
        # 方法2: 从页面文本正则匹配
        try:
            page_content = await page.content()
            # 匹配类似 "qego er4t tr6d nhak u4vm r3cu xgfd 3qqf" 的格式
            pattern = r'(?:[a-zA-Z2-7]{4}\s+){7}[a-zA-Z2-7]{4}'
            matches = re.findall(pattern, page_content)
            
            if not matches:
                # 尝试匹配连续32位
                pattern2 = r'[A-Z2-7]{32}'
                matches = re.findall(pattern2, page_content)
            
            for match in matches:
                cleaned = match.replace(' ', '').strip().upper()
                if len(cleaned) == 32:
                    log(f"从正则匹配提取到密钥")
                    return cleaned
        except:
            pass
        
        # 方法3: 从特定容器提取
        try:
            container = page.locator('[wizard-step-uid*="manualKey"], .qPtGzb, ol.AOmWL')
            if await container.count() > 0:
                text = await container.text_content()
                # 提取32位密钥
                cleaned_text = text.replace(' ', '').upper()
                pattern = r'[A-Z2-7]{32}'
                match = re.search(pattern, cleaned_text)
                if match:
                    log(f"从容器提取到密钥")
                    return match.group()
        except:
            pass
        
        return None
    except Exception as e:
        log(f"提取2FA密钥异常: {e}")
        return None


async def _click_next_button(page: Page, log: Callable) -> bool:
    """
    @brief 循环点击 'Next' 按钮，直到出现验证码输入框
    @details 每隔2秒点击一次，检测是否出现新的2FA验证码输入框
    """
    try:
        # 下一步页面的指示器（验证码输入框 或 Verify 按钮）
        verify_page_indicators = page.locator(
            'input[placeholder*="code" i], '
            'input[placeholder="Enter Code"], '
            'button:has-text("Verify"), '
            '[data-id="dtOep"]'
        )
        
        # 先检查是否已经在下一步页面
        try:
            if await verify_page_indicators.first.is_visible(timeout=2000):
                log("已在验证码输入页面，跳过点击Next")
                return True
        except:
            pass
        
        # 尝试点击 Next 按钮
        clicked = False
        
        # 方式1：通过文本定位
        try:
            btn = page.get_by_text("Next", exact=True)
            if await btn.count() > 0:
                await btn.first.click(force=True, timeout=2000)
                log("✅ 点击 Next 按钮（文本定位）")
                clicked = True
        except:
            pass
        
        # 方式2：通过角色定位
        if not clicked:
            try:
                btn = page.get_by_role("button", name="Next")
                if await btn.count() > 0:
                    await btn.first.click(force=True, timeout=2000)
                    log("✅ 点击 Next 按钮（角色定位）")
                    clicked = True
            except:
                pass
        
        # 方式3：通过 data-id 定位
        if not clicked:
            try:
                btn = page.locator('[data-id="OCpkoe"]')
                if await btn.count() > 0:
                    await btn.first.click(force=True, timeout=2000)
                    log("✅ 点击 Next 按钮（data-id定位）")
                    clicked = True
            except:
                pass
        
        if clicked:
            # 点击成功，等待页面变化
            await asyncio.sleep(2)
            return True
        
        # 如果没点击成功，检查是否已经在验证码页面
        try:
            if await verify_page_indicators.first.is_visible(timeout=2000):
                log("✅ 已在验证码输入页面")
                return True
        except:
            pass
        
        log("❌ 未能点击 Next 按钮")
        return False
            
    except Exception as e:
        log(f"点击Next按钮异常: {e}")
        return False


async def _verify_new_2fa(page: Page, new_2fa_key: str, log: Callable) -> Tuple[bool, Optional[str]]:
    """
    @brief 输入新密钥的验证码
    @return (success, used_code) - 成功标志和实际使用的验证码
    """
    totp = pyotp.TOTP(new_2fa_key)
    
    # 组合所有可能的输入框定位器
    input_placeholder = page.locator('input[placeholder*="code" i]')
    input_enter_code = page.locator('input[placeholder="Enter Code"]')
    input_class = page.locator('input.qdOxv-fmcmS-wGMbrd')
    input_c1 = page.locator('#c1')
    input_text = page.locator('input[type="text"][autocomplete="off"]')
    input_tel = page.locator('input[type="tel"]')
    
    combined_input = (
        input_placeholder
        .or_(input_enter_code)
        .or_(input_class)
        .or_(input_c1)
        .or_(input_text)
        .or_(input_tel)
    )
    
    try:
        # 直接计算当前验证码（重试时不等待，直接使用最新的）
        code = totp.now()
        log(f"新密钥计算的验证码: {code}")
        
        # 智能等待输入框出现
        try:
            await expect(combined_input.first).to_be_visible(timeout=SMART_WAIT_TIMEOUT)
        except:
            log("未找到验证码输入框")
            return False, None
        
        # 清空并填入验证码
        await combined_input.first.fill('')
        await combined_input.first.fill(code)
        log(f"已填入新密钥验证码: {code}")
        return True, code
        
    except Exception as e:
        log(f"验证新2FA异常: {e}")
        return False, None


async def _click_verify_button(page: Page, new_2fa_key: str, log: Callable) -> Tuple[bool, bool]:
    """
    @brief 点击 'Verify' 按钮并检测验证结果
    @details 点击后检测是否验证成功或出现错误
    @param new_2fa_key 新的2FA密钥（用于标识）
    @return (success, need_retry) - 成功标志和是否需要重试
            - (True, False) = 验证成功
            - (False, True) = 验证码错误，需要重试
            - (False, False) = 其他错误，不需要重试
    """
    try:
        clicked = False
        
        # 方式1：通过文本定位
        try:
            btn = page.get_by_text("Verify", exact=True)
            if await btn.count() > 0:
                await btn.first.click(force=True, timeout=2000)
                log("✅ 点击 Verify 按钮（文本定位）")
                clicked = True
        except:
            pass
        
        # 方式2：通过角色定位
        if not clicked:
            try:
                btn = page.get_by_role("button", name="Verify")
                if await btn.count() > 0:
                    await btn.first.click(force=True, timeout=2000)
                    log("✅ 点击 Verify 按钮（角色定位）")
                    clicked = True
            except:
                pass
        
        # 方式3：通过 data-id 定位
        if not clicked:
            try:
                btn = page.locator('[data-id="dtOep"]')
                if await btn.count() > 0:
                    await btn.first.click(force=True, timeout=2000)
                    log("✅ 点击 Verify 按钮（data-id定位）")
                    clicked = True
            except:
                pass
        
        if not clicked:
            log("❌ 未能点击 Verify 按钮")
            return False, False  # 不需要重试，按钮都找不到
        
        # ==================== 关键：检测验证结果 ====================
        log("检测验证结果...")
        
        # 错误提示定位器（验证码错误 - 需要重试）
        # 用户提供的精确选择器：<p class="vqwr2c-W0vJo-fmcmS...">Wrong code. Try again.</p>
        wrong_code_locators = page.locator(
            'p.vqwr2c-W0vJo-fmcmS:has-text("Wrong"), '
            'text="Wrong code. Try again.", '
            'text=/wrong.*code/i, '
            'text=/incorrect.*code/i, '
            '[jsname="xl1FBb"]:has-text("Wrong")'
        )
        
        # 其他错误（不需要重试）
        other_error_locators = page.locator(
            'text=/invalid.*key/i, '
            'text=/error/i, '
            'text=验证码错误, '
            'text=代码错误'
        )
        
        # 成功提示定位器
        success_locators = page.locator(
            'text=/successfully/i, '
            'text=/done/i, '
            'text=/updated/i, '
            'text=/changed/i, '
            'text=成功, '
            'text=已更新, '
            'text=完成'
        )
        
        # 设置页面特征（成功后会跳转回设置页面）
        settings_page = page.get_by_role(
            "button", name=re.compile(r"Change.*authenticator|更改.*身份验证器", re.IGNORECASE)
        )
        
        # 轮询检测结果（最多等待8秒，快速检测错误以便重试）
        for check_attempt in range(8):
            await asyncio.sleep(1)
            
            # 优先检查 "Wrong code" 错误（需要重试）
            try:
                if await wrong_code_locators.count() > 0:
                    for i in range(await wrong_code_locators.count()):
                        try:
                            if await wrong_code_locators.nth(i).is_visible():
                                error_text = await wrong_code_locators.nth(i).text_content()
                                log(f"❌ 检测到验证码错误: {error_text}")
                                return False, True  # 需要重试
                        except:
                            pass
            except:
                pass
            
            # 检查是否回到设置页面（成功的另一种标志）
            try:
                if (await settings_page.first.is_visible(timeout=500)
                        and await page.get_by_role("dialog").count() == 0):
                    log("✅ 已返回设置页面，验证成功")
                    return True, False
            except:
                pass
            
            # 检查 Verify 按钮是否消失（可能成功了）
            try:
                verify_btn = page.locator('button:has-text("Verify"), [data-id="dtOep"]')
                if await verify_btn.count() == 0:
                    # 按钮消失，再等待1秒确认没有错误
                    await asyncio.sleep(1)
                    
                    # 再次检查 "Wrong code" 错误
                    try:
                        if await wrong_code_locators.count() > 0:
                            for i in range(await wrong_code_locators.count()):
                                if await wrong_code_locators.nth(i).is_visible():
                                    error_text = await wrong_code_locators.nth(i).text_content()
                                    log(f"❌ 检测到验证码错误: {error_text}")
                                    return False, True  # 需要重试
                    except:
                        pass
                    
                    log("Verify 按钮已消失，仍需明确设置页面确认")
            except:
                pass
            
            if check_attempt % 3 == 0:
                log(f"等待验证结果... ({check_attempt + 1}/8)")
        
        # 超时后，检查最终状态
        log("⚠️ 验证结果检测超时，进行最终检查...")
        
        # 最终检查 "Wrong code" 错误
        try:
            if await wrong_code_locators.count() > 0:
                for i in range(await wrong_code_locators.count()):
                    if await wrong_code_locators.nth(i).is_visible():
                        error_text = await wrong_code_locators.nth(i).text_content()
                        log(f"❌ 最终检查发现验证码错误: {error_text}")
                        return False, True  # 需要重试
        except:
            pass
        
        # 最终检查是否在设置页面
        try:
            if (await settings_page.first.is_visible(timeout=2000)
                    and await page.get_by_role("dialog").count() == 0):
                log("✅ 最终检查：已在设置页面")
                return True, False
        except:
            pass
        
        log("⚠️ 无法确认验证结果")
        return False, False  # 不确定，不重试
            
    except Exception as e:
        log(f"点击Verify按钮异常: {e}")
        return False, False


# ==================== 批量处理函数 ====================

async def process_change_2fa_batch(
    accounts: List[Dict],
    browser_manager=None,  # 不再使用
    db_manager=None,       # 不再使用
    concurrency: int = 1,
    log_callback: Optional[Callable[[str], None]] = None,
    result_callback: Optional[Callable[[Dict], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None
):
    """
    @brief 批量更改2FA密钥
    @param accounts 账号列表
    @param browser_manager (已弃用，使用 bit_api)
    @param db_manager (已弃用，直接从模块导入)
    @param concurrency 并发数
    @param log_callback 日志回调
    @param result_callback 结果回调
    @param stop_check 停止检查函数
    """
    from playwright.async_api import async_playwright
    
    # 获取比特浏览器API
    try:
        from bit_api import openBrowser, closeBrowser
    except ImportError as e:
        if log_callback:
            log_callback(f"[Change2FA] 导入比特浏览器API失败: {e}")
        return
    
    # 获取数据库管理器
    try:
        from database import DBManager
    except ImportError as e:
        if log_callback:
            log_callback(f"[Change2FA] 导入数据库管理器失败: {e}")
        return
    
    semaphore = asyncio.Semaphore(concurrency)
    
    async def process_one(account: Dict):
        if stop_check and stop_check():
            return
        
        browser_id = account.get('browser_id')
        email = account.get('email', 'Unknown')
        
        async with semaphore:
            if stop_check and stop_check():
                return
            
            playwright_instance = None
            
            try:
                # 打开浏览器
                if log_callback:
                    log_callback(f"[Change2FA] 打开浏览器: {browser_id[:16]}...")
                
                open_result = openBrowser(browser_id)
                if not open_result.get('success'):
                    if result_callback:
                        result_callback({
                            'email': email,
                            'browser_id': browser_id,
                            'success': False,
                            'message': f"打开浏览器失败: {open_result.get('msg', '未知错误')}"
                        })
                    return
                
                # 比特浏览器返回的 ws 字段直接是 WebSocket URL 字符串
                ws_data = open_result.get('data', {}).get('ws')
                # 兼容两种格式：字符串或包含 puppeteer 键的字典
                if isinstance(ws_data, str):
                    ws_endpoint = ws_data
                elif isinstance(ws_data, dict):
                    ws_endpoint = ws_data.get('puppeteer')
                else:
                    ws_endpoint = None
                if not ws_endpoint:
                    if result_callback:
                        result_callback({
                            'email': email,
                            'browser_id': browser_id,
                            'success': False,
                            'message': "无法获取WebSocket连接"
                        })
                    return
                
                # 连接Playwright
                playwright_instance = await async_playwright().start()
                browser = await playwright_instance.chromium.connect_over_cdp(ws_endpoint)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()
                
                # 执行2FA更改
                success, message, new_key = await change_2fa_for_account(
                    page, account, log_callback
                )
                
                # 如果成功，更新数据库
                if success and new_key:
                    try:
                        DBManager.update_account_2fa_key(email, new_key)
                        if log_callback:
                            log_callback(f"[Change2FA] [{email}] 数据库已更新新密钥")
                    except Exception as e:
                        if log_callback:
                            log_callback(f"[Change2FA] [{email}] 更新数据库失败: {e}")
                
                if result_callback:
                    result_callback({
                        'email': email,
                        'browser_id': browser_id,
                        'success': success,
                        'message': message,
                        'new_2fa_key': new_key if success else None
                    })
                
            except Exception as e:
                if log_callback:
                    log_callback(f"[Change2FA] [{email}] 处理异常: {e}")
                if result_callback:
                    result_callback({
                        'email': email,
                        'browser_id': browser_id,
                        'success': False,
                        'message': f"处理异常: {str(e)}"
                    })
            finally:
                # 关闭浏览器
                try:
                    if browser_id:
                        closeBrowser(browser_id)
                        if log_callback:
                            log_callback(f"[Change2FA] 关闭浏览器: {browser_id[:16]}...")
                except:
                    pass
                
                try:
                    if playwright_instance:
                        await playwright_instance.stop()
                except:
                    pass
    
    # 并发执行
    tasks = [process_one(acc) for acc in accounts]
    await asyncio.gather(*tasks, return_exceptions=True)
