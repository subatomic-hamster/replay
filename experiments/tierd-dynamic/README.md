# Tier D experiment C: dynamic reconstruction (Gaussian splatting / 4D)

**Hypothesis.** A dynamic scene representation (shape-of-motion, 4D Gaussians) fitted to
a highlight would give true novel views of moving players.

**Verdict: dead end on this box, not attempted beyond the first blocker.** Every candidate
needs a CUDA or HIP compiler for its rasteriser, and the box has neither. Two candidates
also carry non-commercial or NVIDIA-only dependencies.

## What was run

`gsplat` 1.5.3 (Apache-2.0, nerfstudio-project, pushed 2026-09-19), installed `--no-deps`
into `venvs/tierd`. A 100-Gaussian `gsplat.rasterization(...)` call on the GPU failed:

```
gsplat: No CUDA toolkit found. gsplat will be disabled.
Traceback (most recent call last):
  File ".../gsplat/rendering.py", line 409, in rasterization
    proj_results = fully_fused_projection(
  File ".../gsplat/cuda/_wrapper.py", line 404, in fully_fused_projection
    return _FullyFusedProjectionPacked.apply(
  File ".../gsplat/cuda/_wrapper.py", line 1606, in forward
    camera_model_type = _make_lazy_cuda_obj(
  File ".../gsplat/cuda/_wrapper.py", line 28, in _make_lazy_cuda_obj
    obj = getattr(_C, name_split)
AttributeError: 'NoneType' object has no attribute 'CameraModelType'
```

Cause: gsplat JIT-compiles its kernels on first use. The box has the ROCm *runtime* only,
bundled inside the torch wheel: no `/opt/rocm`, no `hipcc`, no `nvcc`, no `ninja`, and
`torch.utils.cpp_extension.ROCM_HOME` / `CUDA_HOME` are both `None`. gsplat was
uninstalled again.

## Candidates checked (GitHub API, 2026-10-06)

| Candidate | Licence | Blockers here |
|---|---|---|
| gsplat (nerfstudio) | Apache-2.0 | needs a CUDA toolkit (above) |
| AMD-Ecosystem/gsplat-amd (formerly ROCm/gsplat), branch `release/1.5.3b2`, pushed 2026-10-01 | Apache-2.0 | HIP port. Needs the ROCm HIP SDK (`hipcc` plus headers, several GB), more than this run's 2 GB disk budget on a box with 10 to 14 GB free |
| shape-of-motion (vye16) | MIT code | needs gsplat. `requirements.txt` pins NVIDIA RAPIDS (`cudf-cu11`, `cuml-cu11`, ...), which do not exist for ROCm. Preprocessing needs third-party depth / mask / camera / 2D-track models (each with its own licence; the README uses MegaSaM). Last push 2025-08-02 |
| 4DGaussians (hustvl) | Apache-2.0 code | submodules `simple-knn` (Inria) and `depth-diff-gaussian-rasterization` (Inria-derived, **non-commercial**), both CUDA-only |
| Inria gaussian-splatting / diff-gaussian-rasterization | **Inria non-commercial** | CUDA-only. Experiments only by policy (docs/licenses.md) |
| monst3r / dust3r | **CC-BY-NC-SA-4.0** | not attempted: licence, plus experiment B's finding that a tripod gives no parallax |

## What it would take

1. Install the ROCm 7.2 HIP SDK on hfbox (root, several GB; or a container with it) and
   build `gsplat-amd`.
2. Fit a static splat on the plate first (only useful for the real-3D background that
   experiment A already gets from MoGe), then a per-highlight dynamic fit.
3. Expect the same limit as experiments A and B: from one fixed camera, a dynamic fit has
   no observations of the players' far sides. Published monocular 4D methods lean on
   depth and track priors and look right only near the input view, so a ±30° orbit is
   the realistic ceiling.
4. Measure it on the synthetic held-out cameras in `experiments/tierd-pointmaps/eval_synth.py`
   (the scoring there takes any renderer that returns an image and a player mask).
