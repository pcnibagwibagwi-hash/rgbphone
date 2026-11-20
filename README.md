# RGB Phone 2.1 (simple password version)

Folders: `app/` (Android app), `pc_gateway/` (PC side), `tools/make_keystore.py`, `tests/`, `.github/workflows/build.yml`.

Is version mein **PIN, recovery code aur lamba pairing code nahi hai**. Sirf PC ka IP + ek chhota password.
Thodi safety jo rehti hai: sirf ghar ke Wi-Fi par chalta hai, data encrypted hai, galat password
baar-baar daalne par PC thodi der ke liye rok deta hai, PC ka certificate app pehli baar yaad kar leta hai.
(Zyada safety chahiye to purana `add_device.bat` wala lamba code abhi bhi kaam karta hai.)

## A. PC par (ek baar)
1. OpenRGB kholo, SDK Server start rakho.
2. `pc_gateway` folder PC par rakho.
3. `setup_gateway.bat` par **right-click → Run as administrator** (sirf pehli baar; pehle ho chuka ho to chhod do).
4. `set_password.bat` double-click → apna chhota password likho (6-24 akshar: letters, numbers, `-`, `_`; space nahi).
   Password badalna ho to isi ko dobara chalao.
5. `run_gateway.bat` chalao aur khula chhod do. (Roz: OpenRGB + run_gateway.bat.)

## B. Phone par
1. App kholo → PC IP (jaise `192.168.1.8`), port `6743`, password → **Save**. Seedha colour screen khulegi.
2. Settings button se IP/password badal sakte ho. Koi PIN nahi.

## C. Dost ke liye
Dost ko wahi APK do. Uske PC par OpenRGB + `pc_gateway` (A wale steps, apna password) chahiye,
phir uske phone mein uske PC ka IP + uska password. Ye **sirf usi ghar ke Wi-Fi** par chalega.

## D. Signing key / build (jaise pehle)
`tools/make_keystore.py` se key banti hai (backup rakho, GitHub par upload mat karo). GitHub Secrets:
`KEYSTORE_B64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`. Files push karo → Actions →
**RGBPhone-signed-apk** download karo. Purane signed app ke upar seedha update ho jata hai.

## E. Commands (PC)
`python rgb_gateway.py list` · `set-password PASS` · `clear-password` · `add-device NAME` (strict mode) · `revoke NAME`

## Tests
`pip install cryptography` → `python -m unittest discover -s tests -v`
