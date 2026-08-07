FROM docker.io/library/python:3.12-slim AS image-model-builder

RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.8.0 torchvision==0.23.0 \
    && pip install --no-cache-dir onnx==1.18.0

WORKDIR /build
COPY scripts/export_image_model.py /build/export_image_model.py
RUN python /build/export_image_model.py /build/squeezenet1_1.onnx /build/imagenet1k-labels.json


FROM docker.io/library/python:3.12-slim

RUN pip install --no-cache-dir \
    fastapi==0.115.5 \
    numpy==2.3.2 \
    onnxruntime==1.22.1 \
    pillow==11.3.0 \
    uvicorn[standard]==0.34.2 \
    websockets==15.0.1

ENV PYTHONPATH=/app
ENV CODRAWING_IMAGE_MODEL=/app/models/squeezenet1_1.onnx
ENV CODRAWING_IMAGE_MODEL_LABELS=/app/models/imagenet1k-labels.json
WORKDIR /app
COPY --from=image-model-builder /build/squeezenet1_1.onnx /app/models/squeezenet1_1.onnx
COPY --from=image-model-builder /build/imagenet1k-labels.json /app/models/imagenet1k-labels.json
COPY codrawing /app/codrawing

CMD ["python", "-m", "codrawing.game.server"]
