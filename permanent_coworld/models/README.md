# Sketch classifier

`quickdraw_prototypes.json` is a tiny, color-blind classifier generated from the
first 1,500 official Google Quick, Draw! 28×28 bitmaps in each configured class.
It stores one learned mean prototype per class. The raw dataset is streamed with
HTTP range requests by `../scripts/train_quickdraw_model.py`; no source images
or heavyweight training framework remain on disk.

The target is `light bulb`. The other classes are deliberately visually
confusable shapes, so a score above 50% means the board resembles the learned
light-bulb prototype more than the alternatives by a substantial margin.
