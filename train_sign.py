#!/usr/bin/env python3
# =============================================================================
# train_sign.py  —  Tabela sınıflandırıcı eğitimi
#
# Kullanım:
#   python train_sign.py
#   python train_sign.py <veri_klasoru> <cikti_json>
#
# Çıktı: sign_model.json  (ototot-main klasörüne kopyala veya doğrudan oraya yaz)
#
# HOG config: winSize=64×64, blockSize=16×16, blockStride=16×16,
#             cellSize=16×16, nbins=8  →  128 boyut tam olarak
# =============================================================================
import json
import os
import sys

import cv2
import numpy as np

# ---------------------------------------------------------------------------
DATA_DIR   = r"C:\Users\Nitro\Downloads\Compressed\tabelaegitimverisi"
OUTPUT     = os.path.join(os.path.dirname(__file__), "sign_model.json")
IMG_SIZE   = 64
# ---------------------------------------------------------------------------

_HOG = cv2.HOGDescriptor(
    _winSize   =(IMG_SIZE, IMG_SIZE),
    _blockSize =(16, 16),
    _blockStride=(16, 16),
    _cellSize  =(16, 16),
    _nbins     =8,
)


def _hog_feat(gray_64: np.ndarray) -> np.ndarray:
    """64×64 gri görüntüden L2-normalize edilmiş 128-boyutlu HOG vektörü."""
    feat = _HOG.compute(gray_64).flatten().astype(np.float32)
    norm = np.linalg.norm(feat)
    if norm > 0:
        feat /= norm
    return feat


def _preprocess(img_bgr: np.ndarray) -> np.ndarray:
    """BGR görüntüyü 64×64 griye çevir."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)


def _augment(img_bgr: np.ndarray) -> list:
    """Tek görüntüden 6 augmentasyon üret (orijinal dahil)."""
    h, w = img_bgr.shape[:2]
    cx, cy = w // 2, h // 2
    variants = [img_bgr]

    # Rotasyon ±10°
    for angle in (10, -10):
        M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        variants.append(cv2.warpAffine(img_bgr, M, (w, h),
                                       borderMode=cv2.BORDER_REFLECT))

    # Parlaklık ×1.25 / ×0.75
    for alpha in (1.25, 0.75):
        variants.append(
            np.clip(img_bgr.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
        )

    # Yatay flip
    variants.append(cv2.flip(img_bgr, 1))

    return variants   # 6 adet


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    output   = sys.argv[2] if len(sys.argv) > 2 else OUTPUT

    if not os.path.isdir(data_dir):
        sys.exit(f"HATA: klasör bulunamadı → {data_dir}")

    classes = sorted(
        d for d in os.listdir(data_dir)
        if os.path.isdir(os.path.join(data_dir, d))
    )
    if not classes:
        sys.exit("HATA: alt klasör bulunamadı (her sınıf bir klasör olmalı)")

    print(f"Sınıflar ({len(classes)}): {', '.join(classes)}")

    vectors: list = []
    labels:  list = []

    for cls_idx, cls_name in enumerate(classes):
        cls_dir = os.path.join(data_dir, cls_name)
        imgs = [
            f for f in os.listdir(cls_dir)
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))
        ]

        cls_count = 0
        for fname in imgs:
            img = cv2.imread(os.path.join(cls_dir, fname))
            if img is None:
                print(f"  UYARI: {fname} okunamadı, atlandı")
                continue
            for aug in _augment(img):
                feat = _hog_feat(_preprocess(aug))
                vectors.append([round(float(v), 6) for v in feat])
                labels.append(cls_idx)
                cls_count += 1

        print(f"  [{cls_idx}] {cls_name:15s}: {len(imgs)} gorsel -> {cls_count} vektor")

    if not vectors:
        sys.exit("HATA: hiç vektör üretilemedi")

    model = {"classes": classes, "vectors": vectors, "labels": labels}
    with open(output, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False)

    print(f"\nOK  {len(labels)} vektor kaydedildi -> {output}")
    print(f"    Boyut kontrolu: {len(vectors[0])} (128 olmali)")


if __name__ == "__main__":
    main()
