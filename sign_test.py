#!/usr/bin/env python3
"""Webcam sign classifier test — press Q to quit."""
import json, os
import cv2
import numpy as np

MODEL = os.path.join(os.path.dirname(__file__), "sign_model.json")
IMG_SIZE = 64

_HOG = cv2.HOGDescriptor(
    _winSize=(IMG_SIZE, IMG_SIZE), _blockSize=(16,16),
    _blockStride=(16,16), _cellSize=(16,16), _nbins=8,
)

def load_model(path):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    vecs = np.array(m["vectors"], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs /= np.where(norms > 0, norms, 1)
    return m["classes"], vecs, np.array(m["labels"])

def hog_feat(gray64):
    feat = _HOG.compute(gray64).flatten().astype(np.float32)
    n = np.linalg.norm(feat)
    if n > 0: feat /= n
    return feat

def classify(crop_rgb, classes, vecs, labels):
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    feat = hog_feat(gray)
    dists = np.linalg.norm(vecs - feat, axis=1)
    return classes[labels[int(np.argmin(dists))]]

def find_blue_blob(frame_hsv):
    mask = cv2.inRange(frame_hsv, (100,80,50), (140,255,255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5,5), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 500:
        return None
    return cv2.boundingRect(c)

classes, vecs, labels = load_model(MODEL)
print(f"Model loaded: {len(classes)} classes -> {classes}")

cap = cv2.VideoCapture(0)
while True:
    ret, frame = cap.read()
    if not ret:
        break

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    label = "---"
    rect = find_blue_blob(hsv)
    if rect:
        x, y, w, h = rect
        crop = rgb[y:y+h, x:x+w]
        if crop.size > 0:
            label = classify(crop, classes, vecs, labels)
        cv2.rectangle(frame, (x,y), (x+w,y+h), (255,0,0), 2)

    cv2.putText(frame, label, (10,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,200,0), 2)
    cv2.imshow("Sign Test", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
