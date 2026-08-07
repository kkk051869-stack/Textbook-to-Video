from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import traceback
from pathlib import Path


ADAPTATIONS = [
    "Qwen3 thinking text stripped before PresentAgent JSON parsing",
    "text embeddings replaced with deterministic local hash embeddings because Qwen32B endpoint has no embeddings API",
    "frozen source.md and images are reused when available to avoid redundant CPU OCR parsing",
    "frozen refined_doc.json is reused when available to keep long pre-parsed inputs within Qwen32B context limits",
    "vision layout naming replaced with deterministic layout names for text-only Qwen32B",
    "template/source image captions default to filename or nearby text when no VLM is available",
]


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def update_status(path: Path, **updates) -> None:
    if path.exists():
        status = json.loads(path.read_text(encoding="utf-8"))
    else:
        status = {}
    status.update(updates)
    write_json(path, status)


def log_step(status_path: Path, stage: str) -> None:
    print(f"[stage] {stage}", flush=True)
    update_status(status_path, status="running", stage=stage)


def patch_presentagent_for_text_qwen():
    import re

    import torch
    from pptagent.document.element import Media
    import pptagent.induct as induct
    import pptagent.llms as llms
    from pptagent.multimodal import ImageLabler
    from pptagent.model_utils import get_cluster, get_image_embedding, images_cosine_similarity

    original_post_process = llms.LLM.__post_process__
    original_async_call = llms.AsyncLLM.__call__

    def strip_qwen_thinking(response: str) -> str:
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL | re.IGNORECASE)
        return response.strip()

    def post_process_without_thinking(self, response, message, return_json=False, return_message=False):
        response = strip_qwen_thinking(response or "")
        if message and message[-1].get("role") == "assistant":
            message[-1]["content"] = response
        return original_post_process(self, response, message, return_json, return_message)

    async def async_call_without_thinking(self, *args, **kwargs):
        kwargs.setdefault("temperature", 0.2)
        kwargs.setdefault("extra_body", {"chat_template_kwargs": {"enable_thinking": False}})
        return await original_async_call(self, *args, **kwargs)

    async def deterministic_embedding(self, text, encoding_format="float", to_tensor=True, **kwargs):
        if isinstance(text, str):
            items = [text]
        else:
            items = list(text)
        vectors = []
        for item in items:
            digest = hashlib.sha256(str(item).encode("utf-8", errors="ignore")).digest()
            vals = [((digest[i % len(digest)] / 255.0) * 2.0) - 1.0 for i in range(384)]
            vectors.append(vals)
        if to_tensor:
            return torch.tensor(vectors, dtype=torch.float32)
        return vectors

    async def media_caption_fallback_async(self, vision_model):
        if self.caption is None:
            nearby = " ".join(part.strip() for part in (self.near_chunks or ()) if part and part.strip())
            base = Path(self.path).stem if self.path else "source image"
            self.caption = (nearby[:120] if nearby else base) or base
        return self.caption

    async def caption_images_fallback_async(self, vision_model):
        for image, stats in self.image_stats.items():
            stats.setdefault("caption", Path(image).stem)
        self.apply_stats()
        return self.image_stats

    async def layout_split_without_vlm(self, content_slides_index, layout_induction):
        embeddings = get_image_embedding(self.template_image_folder, *self.image_models)
        assert len(embeddings) == len(self.prs)
        content_split = {}
        for slide_idx in content_slides_index:
            slide = self.prs.slides[slide_idx - 1]
            key = (slide.slide_layout_name, slide.get_content_type())
            content_split.setdefault(key, []).append(slide_idx)

        for (layout_name, content_type), slides in content_split.items():
            sub_embeddings = [embeddings[f"slide_{slide_idx:04d}.jpg"] for slide_idx in slides]
            similarity = images_cosine_similarity(sub_embeddings)
            for cluster_no, cluster in enumerate(get_cluster(similarity), start=1):
                slide_indexes = [slides[i] for i in cluster]
                template_id = max(slide_indexes, key=lambda x: len(self.prs.slides[x - 1].shapes))
                cluster_name = f"{layout_name or 'layout'}-{cluster_no}:{content_type}"
                layout_induction[cluster_name]["template_id"] = template_id
                layout_induction[cluster_name]["slides"] = slide_indexes

    ImageLabler.caption_images_async = caption_images_fallback_async
    Media.get_caption_async = media_caption_fallback_async
    llms.LLM.__post_process__ = post_process_without_thinking
    llms.AsyncLLM.__call__ = async_call_without_thinking
    llms.AsyncLLM.get_embedding = deterministic_embedding
    induct.SlideInducterAsync.layout_split = layout_split_without_vlm


async def run_one(modules: dict, lesson_id: str, args: argparse.Namespace) -> int:
    Config = modules["Config"]
    Document = modules["Document"]
    ImageLabler = modules["ImageLabler"]
    ModelManager = modules["ModelManager"]
    Presentation = modules["Presentation"]
    ppt_to_images_async = modules["ppt_to_images_async"]
    parse_pdf = modules["parse_pdf"]
    induct = modules["induct"]
    pptgen = modules["pptgen"]

    experiment = Path(args.experiment_root)
    source_pdf = experiment / "sources" / "frozen" / lesson_id / "source.pdf"
    lesson_out = Path(args.output_root) / lesson_id
    lesson_out.mkdir(parents=True, exist_ok=True)

    if not source_pdf.exists():
        raise FileNotFoundError(source_pdf)

    pdf_md5 = file_md5(source_pdf)
    runs_dir = Path(args.presentagent_repo) / "pptagent" / "runs"
    task_id = f"full-qwen32b/{lesson_id}"
    task_run_dir = runs_dir / task_id
    if task_run_dir.exists() and args.force:
        shutil.rmtree(task_run_dir)

    pdf_dir = runs_dir / "pdf" / pdf_md5
    pptx_dir = runs_dir / "pptx" / "default_template"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pptx_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, pdf_dir / "source.pdf")
    shutil.copy2(Path(args.template), pptx_dir / "source.pptx")
    frozen_md = source_pdf.parent / "source.md"
    frozen_images = source_pdf.parent / "images"
    frozen_refined_doc = source_pdf.parent / "refined_doc.json"
    if frozen_md.exists():
        shutil.copy2(frozen_md, pdf_dir / "source.md")
        if frozen_images.exists():
            dst_images = pdf_dir / "images"
            if dst_images.exists():
                shutil.rmtree(dst_images)
            shutil.copytree(frozen_images, dst_images)
    if frozen_refined_doc.exists():
        shutil.copy2(frozen_refined_doc, pdf_dir / "refined_doc.json")

    generation_config = Config(str(task_run_dir))
    pptx_config = Config(str(pptx_dir))
    parsedpdf_dir = pdf_dir
    ppt_image_folder = pptx_dir / "slide_images"
    task_run_dir.mkdir(parents=True, exist_ok=True)

    task = {"numberOfPages": args.slides, "pptx": "default_template", "pdf": pdf_md5}
    write_json(task_run_dir / "task.json", task)

    status = {
        "lesson_id": lesson_id,
        "status": "running",
        "pipeline": "presentagent_full_pdf_to_ppt",
        "adaptations": ADAPTATIONS,
        "source_pdf": str(source_pdf),
        "source_pdf_sha256": file_sha256(source_pdf),
        "slides": args.slides,
        "presentagent_runs_dir": str(task_run_dir),
    }
    status_path = lesson_out / "run_status.json"
    write_json(status_path, status)

    models = ModelManager(
        api_base=args.api_base,
        language_model_name=args.model,
        vision_model_name=args.model,
        text_model_name=args.model,
    )

    log_step(status_path, "ppt parsing")
    presentation = Presentation.from_file(str(pptx_dir / "source.pptx"), pptx_config)
    if not ppt_image_folder.exists() or len(list(ppt_image_folder.iterdir())) != len(presentation):
        await ppt_to_images_async(str(pptx_dir / "source.pptx"), str(ppt_image_folder))
        expected = len(presentation) + len(presentation.error_history)
        actual = len(list(ppt_image_folder.iterdir()))
        if actual != expected:
            raise RuntimeError(f"template image count mismatch: expected {expected}, got {actual}")
        for err_idx, _ in presentation.error_history:
            (ppt_image_folder / f"slide_{err_idx:04d}.jpg").unlink(missing_ok=True)
        for i, slide in enumerate(presentation.slides, 1):
            slide.slide_idx = i
            src = ppt_image_folder / f"slide_{slide.real_idx:04d}.jpg"
            dst = ppt_image_folder / f"slide_{slide.slide_idx:04d}.jpg"
            if src != dst and src.exists():
                src.rename(dst)

    labler = ImageLabler(presentation, pptx_config)
    image_stats_path = pptx_dir / "image_stats.json"
    if image_stats_path.exists():
        labler.apply_stats(json.loads(image_stats_path.read_text(encoding="utf-8")))
    else:
        await labler.caption_images_async(models.vision_model)
        write_json(image_stats_path, labler.image_stats)

    log_step(status_path, "pdf parsing")
    source_md = parsedpdf_dir / "source.md"
    if source_md.exists():
        text_content = source_md.read_text(encoding="utf-8")
    else:
        text_content = parse_pdf(str(parsedpdf_dir / "source.pdf"), str(parsedpdf_dir), models.marker_model)
    update_status(status_path, source_markdown=str(source_md))

    log_step(status_path, "document refine")
    refined_doc_path = parsedpdf_dir / "refined_doc.json"
    if refined_doc_path.exists():
        source_doc = Document.from_dict(json.loads(refined_doc_path.read_text(encoding="utf-8")), str(parsedpdf_dir))
    else:
        source_doc = await Document.from_markdown_async(
            text_content,
            models.language_model,
            models.vision_model,
            str(parsedpdf_dir),
        )
        write_json(refined_doc_path, source_doc.to_dict())

    log_step(status_path, "ppt analysis")
    slide_induction_path = pptx_dir / "slide_induction.json"
    if slide_induction_path.exists():
        slide_induction = json.loads(slide_induction_path.read_text(encoding="utf-8"))
    else:
        template_pptx = pptx_dir / "template.pptx"
        template_images = pptx_dir / "template_images"
        from copy import deepcopy

        deepcopy(presentation).save(str(template_pptx), layout_only=True)
        await ppt_to_images_async(str(template_pptx), str(template_images))
        slide_inducter = induct.SlideInducterAsync(
            presentation,
            str(ppt_image_folder),
            str(template_images),
            pptx_config,
            models.image_model,
            models.language_model,
            models.vision_model,
        )
        layout_induction = await slide_inducter.layout_induct()
        slide_induction = await slide_inducter.content_induct(layout_induction)
        write_json(slide_induction_path, slide_induction)

    log_step(status_path, "ppt generation")
    ppt_agent = pptgen.PPTAgentAsync(
        models.text_model,
        models.language_model,
        models.vision_model,
        error_exit=False,
        retry_times=5,
    )
    ppt_agent.set_reference(
        config=generation_config,
        slide_induction=slide_induction,
        presentation=presentation,
    )

    prs, history = await ppt_agent.generate_pres(
        source_doc=source_doc,
        num_slides=args.slides,
    )
    if prs is None:
        raise RuntimeError("PresentAgent returned no presentation")
    final_pptx = task_run_dir / "final.pptx"
    prs.save(str(final_pptx))
    write_json(task_run_dir / "history.json", history)

    if not final_pptx.exists():
        status["status"] = "failed"
        status["error"] = "PresentAgent did not produce final.pptx"
        write_json(status_path, status)
        return 1

    shutil.copy2(final_pptx, lesson_out / "generated_full_presentagent.pptx")
    for extra in ["task.json", "agent_steps.json", "history.json"]:
        src = task_run_dir / extra
        if src.exists():
            shutil.copy2(src, lesson_out / extra)
    status["status"] = "completed"
    status["stage"] = "completed"
    status["generated_pptx"] = str(lesson_out / "generated_full_presentagent.pptx")
    status["generated_pptx_sha256"] = file_sha256(lesson_out / "generated_full_presentagent.pptx")
    write_json(status_path, status)
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-root", default="/ai/data/textbook-to-video/experiments/presentagent-comparison-v1")
    parser.add_argument("--output-root", default="/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/runs/presentagent_full_qwen32b")
    parser.add_argument("--presentagent-repo", default="/ai/data/repos/PresentAgent")
    parser.add_argument("--template", default="/ai/data/repos/PresentAgent/resource/templates/default_template.pptx")
    parser.add_argument("--slides", type=int, default=7)
    parser.add_argument("--lessons", nargs="*", default=None)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="qwen3-32b-awq")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")
    os.environ["API_BASE"] = args.api_base
    os.environ["LANGUAGE_MODEL"] = args.model
    os.environ["VISION_MODEL"] = args.model
    os.environ["TEXT_MODEL"] = args.model

    repo = Path(args.presentagent_repo)
    sys.path.insert(0, str(repo))
    os.chdir(repo)

    import pptagent.induct as induct
    import pptagent.pptgen as pptgen
    from pptagent.document import Document
    from pptagent.model_utils import ModelManager, parse_pdf
    from pptagent.multimodal import ImageLabler
    from pptagent.presentation import Presentation
    from pptagent.utils import Config, ppt_to_images_async

    patch_presentagent_for_text_qwen()
    modules = {
        "Config": Config,
        "Document": Document,
        "ImageLabler": ImageLabler,
        "ModelManager": ModelManager,
        "Presentation": Presentation,
        "ppt_to_images_async": ppt_to_images_async,
        "parse_pdf": parse_pdf,
        "induct": induct,
        "pptgen": pptgen,
    }

    if args.lessons:
        lessons = args.lessons
    else:
        source_root = Path(args.experiment_root) / "sources" / "frozen"
        lessons = sorted(p.name for p in source_root.iterdir() if (p / "source.pdf").exists())

    failures = 0
    for lesson_id in lessons:
        print(f"=== {lesson_id} ===", flush=True)
        try:
            failures += await run_one(modules, lesson_id, args)
        except Exception as exc:
            failures += 1
            out = Path(args.output_root) / lesson_id
            write_json(
                out / "run_status.json",
                {
                    "lesson_id": lesson_id,
                    "status": "failed",
                    "pipeline": "presentagent_full_pdf_to_ppt",
                    "adaptations": ADAPTATIONS,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            print(f"FAIL {lesson_id}: {exc}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
