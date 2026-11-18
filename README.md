# RGB Phone 2.0 (secure version)

Folders: `app/` (Android app), `pc_gateway/` (PC side), `tools/make_keystore.py`, `tests/`, `.github/workflows/build.yml`.
Pehle `SECURITY.md` padho (har fix wahan samjhaya hai).

## A. PC par (ek baar)
1. OpenRGB kholo → **SDK Server** tab → **Start Server**. (Ye PC par hi rahega, ab bahar se nahi dikhega.)
2. Is project ka `pc_gateway` folder PC par rakho (jaise `C:\rgb\pc_gateway`).
3. `setup_gateway.bat` par **right-click → Run as administrator**. Ye purana unsafe port-forward aur firewall rule "OpenRGB SDK" hata deta hai, naya rule "RGB Gateway" lagata hai, aur certificate banata hai. (Python 3 installed hona chahiye.)
4. `add_device.bat` double-click → phone ka naam likho (jaise `myphone`) → ek lamba code `RGB1....` aayega. Use copy karo (ye sirf ek baar dikhta hai).
5. `run_gateway.bat` chalao aur khula chhod do. (Roz ke liye: OpenRGB + run_gateway.bat.)

## B. Signing key (ek baar)
1. PC par: `pip install cryptography` phir `python tools\make_keystore.py`.
2. Ye `rgbphone-release.p12` banata hai. **Ise pendrive par backup rakho, GitHub par upload mat karo.** Key kho di to app update nahi hoga.
3. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**. 4 secrets banao (naam bilkul aise): `KEYSTORE_B64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`. Values script ne print ki hain.

## C. GitHub par update
1. Repo me purani root `main.py` aur purana `buildozer.spec` / `.github` **delete** karo.
2. Is project ke andar ki saari files/folders (`app`, `pc_gateway`, `tools`, `tests`, `.github`, `buildozer.spec`, README, SECURITY) upload karo → Commit.
3. **Actions** tab → "Build signed release APK" green hone do → neeche **Artifacts → RGBPhone-signed-apk** download karo.
4. Phone se purana app uninstall karo (naya key alag hai) → naya APK install karo.

## D. Phone par
1. App kholo → PC IP (`192.168.1.8`), port `6743`, pairing code paste, apna PIN (6–12 digit) → Save.
2. **Recovery code kagaz par likh lo.**
3. Colour ring, brightness, presets, Rainbow, Off pehle jaise.

## Naya phone / phone kho gaya
`python rgb_gateway.py list` · `python rgb_gateway.py revoke myphone` · `add_device.bat` naye phone ke liye.

## Tests
`pip install cryptography` → `python -m unittest discover -s tests -v`
