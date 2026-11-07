"""Write a private evaluate_script function that fills the Mars login form from secret files.

Usage: python3 -I make_login.py OUT.js LOGIN_FILE PASSWORD_FILE
OUT.js is created with mode 600; delete it right after evaluate_script. Prints no secret.
"""
import json
import os
import sys

out, login_file, password_file = sys.argv[1:4]
login = open(login_file).read().rstrip("\r\n")
password = open(password_file).read().rstrip("\r\n")

js = """() => {
  const L = %s, P = %s;
  const inputs = [...document.querySelectorAll('form input')];
  const user = inputs.find(i => i.type !== 'password' && i.type !== 'hidden');
  const pass = inputs.find(i => i.type === 'password');
  if (!user || !pass) return {ok: false, reason: 'inputs not found', count: inputs.length};
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  for (const [el, v] of [[user, L], [pass, P]]) {
    el.focus(); setter.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  const btn = [...document.querySelectorAll('form button')].find(b => b.textContent.trim() === 'Войти');
  if (!btn) return {ok: false, reason: 'button not found'};
  btn.click();
  return {ok: true};
}""" % (json.dumps(login), json.dumps(password))

fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(js)
