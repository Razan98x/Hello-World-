from flask import Flask, request, jsonify
from paddleocr import PaddleOCR
import base64, io, os
from PIL import Image, ImageEnhance, ImageOps

app = Flask(__name__)

# ✅ ضمان CORS headers دائمًا
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return response

# ✅ OCR بالإنجليزي + العربي (غالبًا الفواتير مختلطة)
ocr_en = PaddleOCR(lang="en", use_textline_orientation=True)
ocr_ar = PaddleOCR(lang="ar", use_textline_orientation=True)

def preprocess_pil(img: Image.Image) -> Image.Image:
    # 1) RGB (حل RGBA/PNG)
    img = img.convert("RGB")

    # 2) قص حدود بيضاء (اختياري مفيد للفواتير)
    img = ImageOps.autocontrast(img)

    # 3) تكبير للصورة (يعزز OCR للأرقام)
    scale = 2
    img = img.resize((img.width * scale, img.height * scale))

    # 4) رفع التباين والحدة
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = ImageEnhance.Sharpness(img).enhance(2.0)

    return img

def run_ocr(ocr, img_path: str):
    # بعض الإصدارات تفضل predict
    try:
        return ocr.predict(img_path)
    except Exception:
        return ocr.ocr(img_path)

def parse_result_to_text(result):
    extracted = []
    confs = []

    if not result:
        return "", 0.0

    # PaddleOCR outputs تختلف حسب الإصدار
    # نحاول نتعامل مع الشائع:
    for block in result:
        # block ممكن يكون list lines أو dict
        if isinstance(block, list):
            for line in block:
                # line: [box, (text, score)]
                if isinstance(line, list) and len(line) >= 2:
                    text, score = line[1][0], float(line[1][1])
                    extracted.append(text)
                    confs.append(score)
        elif isinstance(block, dict) and "rec_text" in block:
            # بعض نسخ predict ترجع dicts
            extracted.append(block.get("rec_text", ""))
            confs.append(float(block.get("rec_score", 0.0)))

    avg_conf = sum(confs)/len(confs) if confs else 0.0
    return " ".join(extracted).strip(), avg_conf

@app.route("/ocr", methods=["POST", "OPTIONS"])
def ocr_route():
    if request.method == "OPTIONS":
        return ("", 200)

    tmp = "temp.png"  # ✅ PNG أفضل للنص
    try:
        data = request.get_json(force=True)
        img_data = data.get("image", "")

        if "," in img_data:
            img_data = img_data.split(",")[1]

        img_bytes = base64.b64decode(img_data)
        img = Image.open(io.BytesIO(img_bytes))

        # ✅ preprocessing
        img = preprocess_pil(img)

        # ✅ حفظ PNG
        img.save(tmp)

        # ✅ OCR مرتين (EN ثم AR) ونجمع النص
        res_en = run_ocr(ocr_en, tmp)
        text_en, conf_en = parse_result_to_text(res_en)

        res_ar = run_ocr(ocr_ar, tmp)
        text_ar, conf_ar = parse_result_to_text(res_ar)

        # دمج ذكي: خذي الأكثر ثقة + ضيفي الثاني
        if conf_en >= conf_ar:
            final_text = (text_en + " " + text_ar).strip()
            final_conf = conf_en
        else:
            final_text = (text_ar + " " + text_en).strip()
            final_conf = conf_ar

        return jsonify({
            "success": True,
            "text": final_text,
            "confidence": round(final_conf, 3)
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
