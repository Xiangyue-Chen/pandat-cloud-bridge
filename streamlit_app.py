from __future__ import annotations

import math
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID


SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import streamlit as st

from pandat_bridge.github_api import GitHubBroker, RunState, RunnerState, WorkflowRun
from pandat_bridge.models import JobSpec, JobValidationError


PAGE_TITLE = "Pandat 云端计算桥"


def build_job_from_rows(
    sample_name: str,
    unit: str,
    rows: Sequence[Mapping[str, object]] | pd.DataFrame,
    temperature_start_c: float,
    temperature_end_c: float,
    steps: int,
    pressure_atm: float,
) -> JobSpec:
    records = rows.to_dict("records") if isinstance(rows, pd.DataFrame) else list(rows)
    composition: list[dict[str, object]] = []
    for row in records:
        element = row.get("元素")
        value = row.get("含量")
        if not isinstance(element, str) or not element.strip():
            continue
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        composition.append({"element": element.strip(), "value": value})
    return JobSpec.from_mapping(
        {
            "sample_name": sample_name,
            "unit": unit,
            "composition": composition,
            "temperature_start_c": temperature_start_c,
            "temperature_end_c": temperature_end_c,
            "steps": steps,
            "pressure_atm": pressure_atm,
        }
    )


def submit_job(
    session: MutableMapping[str, object], broker: GitHubBroker, job: JobSpec
) -> WorkflowRun:
    run = broker.dispatch(job)
    session.clear()
    session.update(
        {
            "current_job_id": str(job.job_id),
            "current_run_id": run.run_id,
            "current_run_url": run.html_url,
            "current_status": "queued",
            "current_conclusion": None,
        }
    )
    return run


def fetch_current_artifact(
    session: Mapping[str, object], broker: GitHubBroker
) -> tuple[bytes, str]:
    run_id = int(session["current_run_id"])
    job_id = UUID(str(session["current_job_id"]))
    if session.get("current_status") != "completed" or session.get("current_conclusion") != "success":
        raise ValueError("current job has not completed successfully")
    data = broker.download_artifact(run_id, job_id)
    return data, f"pandat-result-{job_id}.zip"


def runner_status_text(state: RunnerState) -> str:
    if not state.online:
        return "本机计算代理离线；提交后任务会在 GitHub 排队，等本机 runner 上线。"
    if state.busy:
        return f"本机计算代理 {state.name or ''} 正在计算中，新任务将排队。"
    return f"本机计算代理 {state.name or ''} 在线，可以接收任务。"


def _broker_from_secrets() -> GitHubBroker:
    github = _secret_section("github")
    return GitHubBroker(
        token=str(github.get("token", "")),
        owner=str(github.get("owner", "")),
        repo=str(github.get("repo", "")),
        workflow=str(github.get("workflow", "pandat-calculate.yml")),
        ref=str(github.get("ref", "main")),
    )


def _refresh_run(broker: GitHubBroker) -> RunState:
    state = broker.get_run(int(st.session_state["current_run_id"]))
    st.session_state["current_status"] = state.status
    st.session_state["current_conclusion"] = state.conclusion
    st.session_state["current_run_url"] = state.html_url
    return state


def render() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="⚗️", layout="wide")
    st.title(PAGE_TITLE)
    st.caption("网页负责排队和回传；计算由持有 Pandat 许可证与数据库的 Windows 本机完成。")
    st.info("本机通过出站 HTTPS 主动连接 GitHub，不开放本地端口。")

    st.subheader("1 · 填写计算条件")
    default_rows = pd.DataFrame(
        [
            {"元素": "Fe", "含量": 57.93},
            {"元素": "Co", "含量": 9.66},
            {"元素": "Ni", "含量": 26.28},
            {"元素": "Cr", "含量": 1.10},
            {"元素": "Ti", "含量": 4.97},
            {"元素": "B", "含量": 0.05},
        ]
    )
    with st.form("pandat-job"):
        sample_name = st.text_input("样品名称", value="C63(C9)")
        unit_label = st.radio("成分单位", ["at.%", "wt.%"], horizontal=True)
        rows = st.data_editor(
            default_rows,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "元素": st.column_config.TextColumn("元素", help="元素符号，例如 Fe、Ni、Cr"),
                "含量": st.column_config.NumberColumn("含量", min_value=0.0, format="%.8g"),
            },
        )
        left, middle, right, pressure_col = st.columns(4)
        with left:
            start = st.number_input("起始温度 (℃)", value=25.0)
        with middle:
            end = st.number_input("终止温度 (℃)", value=1500.0)
        with right:
            steps = st.number_input("步数", min_value=2, max_value=2000, value=100, step=1)
        with pressure_col:
            pressure = st.number_input("压力 (atm)", min_value=0.000001, value=1.0, format="%.6g")
        submitted = st.form_submit_button("提交计算", type="primary", use_container_width=True)

    if submitted:
        try:
            job = build_job_from_rows(
                sample_name,
                "at" if unit_label == "at.%" else "wt",
                rows,
                float(start),
                float(end),
                int(steps),
                float(pressure),
            )
            broker = _broker_from_secrets()
            runner_state = broker.get_runner_state("pandat-licensed")
            message = runner_status_text(runner_state)
            if runner_state.online:
                st.success(message)
            else:
                st.warning(message)
            run = submit_job(st.session_state, broker, job)
            st.success(f"任务已提交：{job.job_id}")
            st.link_button("在 GitHub 查看作业", run.html_url)
        except (JobValidationError, ValueError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"任务提交失败：{exc}")

    st.subheader("2 · 查看状态与下载")
    run_id = st.session_state.get("current_run_id")
    if not run_id:
        st.caption("提交后，这里会显示 GitHub 队列状态和结果下载。")
        return
    st.write(f"作业 ID：`{st.session_state.get('current_job_id')}`")
    st.write(f"GitHub run：`{run_id}`")
    if st.button("刷新状态"):
        try:
            state = _refresh_run(_broker_from_secrets())
            st.success(f"状态：{state.status} / {state.conclusion or '尚未结束'}")
        except Exception as exc:
            st.error(f"状态查询失败：{exc}")
    if st.session_state.get("current_status") == "completed":
        conclusion = st.session_state.get("current_conclusion")
        if conclusion == "success":
            if st.button("获取计算结果"):
                try:
                    data, filename = fetch_current_artifact(st.session_state, _broker_from_secrets())
                    st.session_state["current_artifact"] = data
                    st.session_state["current_artifact_name"] = filename
                except Exception as exc:
                    st.error(f"结果下载失败：{exc}")
        else:
            st.error(f"本次作业结束但未成功：{conclusion}")
    if isinstance(st.session_state.get("current_artifact"), bytes):
        st.download_button(
            "下载结果 ZIP",
            data=st.session_state["current_artifact"],
            file_name=str(st.session_state.get("current_artifact_name", "pandat-result.zip")),
            mime="application/zip",
            use_container_width=True,
        )
    st.caption("输出是 Pandat 热力学平衡预测，不等于实际冷却组织或实验验证。")


def _secret_section(name: str) -> Mapping[str, Any]:
    try:
        value = st.secrets[name]
    except (FileNotFoundError, KeyError):
        return {}
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    render()

