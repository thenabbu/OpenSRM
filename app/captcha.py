"""Portal constants + the ddddocr captcha solver.

Extracted from app/app.py (facade pump, phase 3). These are pure portal trivia —
the login URL, the JS that grabs the captcha blob, and the OCR singleton — with
no dependency on the app at all, so the scraper can import them directly
instead of reaching through the facade.

Re-exported from app.app for existing callers.
"""
import base64

LOGIN_URL = "https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp"

_solver = None
def get_solver():
    global _solver
    if _solver is None:
        import ddddocr
        _solver = ddddocr.DdddOcr(beta=True)
    return _solver

def solve_captcha_b64(b64):
    return get_solver().classification(base64.b64decode(b64))

CAPTCHA_JS = """async () => {
    const img = document.querySelector('img[alt="Captcha"]');
    // The captcha blob may not have painted yet — a 0x0 canvas yields a
    // blank image and a garbage OCR read, so the login always fails the
    // captcha. Poll until the image actually has dimensions.
    for (let i = 0; i < 40; i++) {
        if (img && img.complete && img.naturalWidth > 0) {
            const c = document.createElement('canvas');
            c.width = img.naturalWidth; c.height = img.naturalHeight;
            c.getContext('2d').drawImage(img, 0, 0);
            return c.toDataURL('image/png').split(',')[1];
        }
        await new Promise(r => setTimeout(r, 100));
    }
    return null;
}"""
