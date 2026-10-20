"""Streamlit dashboard for Althea AI Evidence & Verification."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Callable

import streamlit as st
import streamlit.components.v1 as components

from althea_evidence_ui.exports import claims_csv, snapshot_json
from althea_evidence_ui.validation import is_valid_http_url


def _format_time(seconds: float | int | None) -> str:
    """Format seconds into mm:ss."""
    if seconds is None:
        return "00:00"
    try:
        s = float(seconds)
        mins = int(s // 60)
        secs = int(s % 60)
        return f"{mins:02d}:{secs:02d}"
    except Exception:
        return "00:00"


def render_app(backends: dict[str, Callable[[], Any]]) -> None:
    """
    Render the Althea AI Streamlit dashboard.

    `backends` maps a mode label (e.g. 'Sample demo (Fixture)') to a zero-argument backend factory.
    """
    st.set_page_config(
        page_title="Althea AI — Evidence & Dashboard",
        page_icon="⚖️",
        layout="wide",
    )

    # Initialize session state
    if "backend_instances" not in st.session_state:
        st.session_state.backend_instances = {}
    if "current_job_id" not in st.session_state:
        st.session_state.current_job_id = None
    if "selected_pairs" not in st.session_state:
        st.session_state.selected_pairs = set()

    # Sidebar: Mode and Job Management
    with st.sidebar:
        st.title("⚖️ Althea AI")
        st.caption("Factual Disagreement & Evidence Verification")

        mode_options = list(backends.keys())
        selected_mode = st.selectbox("Execution Mode", mode_options, index=0)

        # Lazy instantiate backend once per mode
        if selected_mode not in st.session_state.backend_instances:
            st.session_state.backend_instances[selected_mode] = backends[selected_mode]()
        backend = st.session_state.backend_instances[selected_mode]

        # Mode indicator badge
        mode_str = getattr(backend, "mode", "fixture")
        if mode_str == "fixture":
            st.info("🟡 **Mode: Offline Fixture** (Zero external network calls)")
        else:
            st.success("🟢 **Mode: Live Vertex Gemini**")

        st.divider()

        # Job history
        st.subheader("Saved Jobs")
        try:
            jobs_list = backend.list_jobs(limit=20)
        except Exception as e:
            jobs_list = []
            st.error(f"Failed to load jobs: {e}")

        if jobs_list:
            job_choices = {f"{j['title']} ({j['status']}) — {j['job_id'][:8]}": j["job_id"] for j in jobs_list}
            selected_job_label = st.selectbox(
                "Select Job",
                list(job_choices.keys()),
                index=0,
            )
            selected_job_id = job_choices[selected_job_label]
            if selected_job_id != st.session_state.current_job_id:
                st.session_state.current_job_id = selected_job_id
                st.session_state.selected_pairs = set()
        else:
            st.caption("No saved jobs yet.")

    # Load current job snapshot if available
    current_snapshot = None
    if st.session_state.current_job_id:
        try:
            current_snapshot = backend.load(st.session_state.current_job_id)
        except Exception as e:
            st.error(f"Error loading job {st.session_state.current_job_id}: {e}")

    # Top Section: Input / Analysis Area
    with st.expander("📥 New Input & Analysis", expanded=(current_snapshot is None)):
        col_input, col_config = st.columns([2, 1])

        with col_input:
            input_source_type = st.radio(
                "Input Type",
                ["Sample Dataset", "Audio File (.mp3/.wav)", "Transcript JSON"],
                horizontal=True,
            )

            job_title = st.text_input("Job Title", value="Riverton Debate Sample" if input_source_type == "Sample Dataset" else "Uploaded Recording")

            source_payload: dict[str, Any] = {"title": job_title}

            if input_source_type == "Sample Dataset":
                st.markdown("**Sample:** `riverton_demo` (Fictional two-speaker city budget & unemployment debate)")
                source_payload.update({
                    "kind": "sample",
                    "sample_id": "riverton_demo",
                })
            elif input_source_type == "Audio File (.mp3/.wav)":
                uploaded_file = st.file_uploader("Upload Audio (Max 5 mins / 20 MiB)", type=["mp3", "wav"])
                if uploaded_file:
                    if uploaded_file.size > 20 * 1024 * 1024:
                        st.error("Uploaded file exceeds 20 MiB limit.")
                    else:
                        st.info("File uploaded. In standalone fixture mode, audio analysis requires live integration.")
                        source_payload.update({
                            "kind": "audio",
                            "original_filename": uploaded_file.name,
                        })
            else:
                uploaded_json = st.file_uploader("Upload Transcript JSON", type=["json"])
                if uploaded_json:
                    try:
                        parsed_json = json.load(uploaded_json)
                        source_payload.update({
                            "kind": "transcript",
                            "transcript_data": parsed_json,
                        })
                        st.success("Valid transcript JSON loaded.")
                    except Exception as e:
                        st.error(f"Invalid JSON: {e}")

        with col_config:
            st.markdown("### Settings")
            verify_on_run = st.checkbox("Check up to 4 disagreements against web evidence immediately", value=True)

            status_box = st.empty()
            if st.button("🚀 Run Analysis", type="primary", use_container_width=True):
                with st.spinner("Processing analysis..."):
                    def _progress_cb(msg: str):
                        status_box.info(msg)

                    try:
                        new_snapshot = backend.run(source_payload, verify=verify_on_run, progress=_progress_cb)
                        st.session_state.current_job_id = new_snapshot["job_id"]
                        st.session_state.selected_pairs = set()
                        current_snapshot = new_snapshot
                        st.success("Analysis complete!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")

    if not current_snapshot:
        st.info("Select or create a job above to view details.")
        return

    # Job header bar
    st.subheader(f"📌 {current_snapshot.get('title', 'Job')} `{current_snapshot.get('job_id', '')[:8]}`")
    status_label = current_snapshot.get("status", "ready")
    st.caption(f"Status: **{status_label.upper()}** | Updated: `{current_snapshot.get('updated_at', '')}`")

    # Display any top-level issues
    for issue in current_snapshot.get("issues", []):
        st.warning(f"⚠️ **[{issue.get('stage', '').upper()} - {issue.get('code', '')}]**: {issue.get('message', '')}")

    transcript = current_snapshot.get("transcript")
    analysis = current_snapshot.get("analysis")
    verification = current_snapshot.get("verification")

    # 4 Required Tabs
    tab_transcript, tab_claims, tab_disagreements, tab_evidence = st.tabs([
        "📜 Transcript",
        "📋 Claims",
        "⚡ Disagreements",
        "🔍 Evidence & Export",
    ])

    # ----------------------------------------------------
    # TAB 1: TRANSCRIPT
    # ----------------------------------------------------
    with tab_transcript:
        if not transcript:
            st.info("No transcript available for this job.")
        else:
            st.markdown("### Transcript Timeline & Speaker Review")
            st.caption(f"Language: **{transcript.get('language', 'en')}** | Duration: **{_format_time(transcript.get('duration_s'))}** | Origin: **{transcript.get('origin', '')}**")

            # Audio Player check
            audio_rel = transcript.get("source", {}).get("audio_relpath")
            data_dir = getattr(backend, "settings", {}).get("data_dir", "./data")
            audio_playable = False
            if audio_rel:
                abs_audio_path = Path(data_dir) / audio_rel
                if abs_audio_path.is_file():
                    audio_playable = True
                    st.audio(str(abs_audio_path))
            if not audio_playable:
                st.caption("🎵 *Audio unavailable (Fictional transcript sample or unlinked file)*")

            # Speaker color map
            speakers = transcript.get("speakers", [])
            speaker_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
            speaker_color_map = {
                sp["speaker_id"]: speaker_colors[i % len(speaker_colors)]
                for i, sp in enumerate(speakers)
            }
            speakers_map = {sp["speaker_id"]: sp.get("display_name", sp["speaker_id"]) for sp in speakers}

            # Chronological display of segments
            st.markdown("#### Chronological Transcript Turns")
            for seg in transcript.get("segments", []):
                sp_id = seg.get("speaker_id", "")
                sp_name = speakers_map.get(sp_id, sp_id)
                color = speaker_color_map.get(sp_id, "#333333")
                t_start = _format_time(seg.get("start_s"))
                t_end = _format_time(seg.get("end_s"))

                st.markdown(
                    f"<div style='border-left: 4px solid {color}; padding-left: 10px; margin-bottom: 8px;'>"
                    f"<b>{sp_name}</b> <span style='color: gray; font-size: 0.85em;'>[{t_start} – {t_end}]</span><br/>"
                    f"{seg.get('text', '')}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # Review & Edit Form
            st.divider()
            with st.expander("✏️ Edit Transcript & Speakers (Human Review)"):
                st.warning("⚠️ Edits are marked as human-reviewed. Saving invalidates downstream claims, disagreements, and verification.")

                with st.form("transcript_review_form"):
                    st.markdown("##### Speaker Display Names")
                    new_speaker_names = {}
                    col_sp1, col_sp2 = st.columns(2)
                    for idx, sp in enumerate(speakers):
                        target_col = col_sp1 if idx % 2 == 0 else col_sp2
                        new_name = target_col.text_input(
                            f"Display name for {sp['speaker_id']}",
                            value=sp.get("display_name", ""),
                            key=f"sp_name_{sp['speaker_id']}",
                        )
                        new_speaker_names[sp["speaker_id"]] = new_name

                    st.markdown("##### Segments Text & Timing")
                    edited_segments = []
                    for seg in transcript.get("segments", []):
                        seg_id = seg.get("segment_id")
                        c_time, c_text = st.columns([1, 3])
                        with c_time:
                            st.caption(f"Segment: `{seg_id}`")
                            start_val = st.number_input(
                                f"Start (s) [{seg_id}]",
                                value=float(seg.get("start_s", 0.0)),
                                step=0.5,
                                key=f"start_{seg_id}",
                            )
                            end_val = st.number_input(
                                f"End (s) [{seg_id}]",
                                value=float(seg.get("end_s", 0.0)),
                                step=0.5,
                                key=f"end_{seg_id}",
                            )
                        with c_text:
                            text_val = st.text_area(
                                f"Text [{seg_id}]",
                                value=seg.get("text", ""),
                                height=68,
                                key=f"text_{seg_id}",
                            )

                        edited_segments.append({
                            "segment_id": seg_id,
                            "speaker_id": seg.get("speaker_id"),
                            "start_s": start_val,
                            "end_s": end_val,
                            "text": text_val,
                        })

                    submitted_review = st.form_submit_button("💾 Save Human Review")
                    if submitted_review:
                        # Construct updated transcript
                        new_speakers = [
                            {"speaker_id": s["speaker_id"], "display_name": new_speaker_names.get(s["speaker_id"], s["speaker_id"])}
                            for s in speakers
                        ]
                        updated_tr = dict(transcript)
                        updated_tr["speakers"] = new_speakers
                        updated_tr["segments"] = edited_segments
                        try:
                            saved_snapshot = backend.save_review(current_snapshot["job_id"], updated_tr)
                            st.session_state.current_job_id = saved_snapshot["job_id"]
                            st.success("Transcript review saved! Downstream artifacts invalidated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error saving review: {e}")

            # Reanalyze button when in ready status
            if current_snapshot.get("status") == "ready" or analysis is None:
                st.divider()
                st.info("Downstream analysis is cleared. Click below to reanalyze the reviewed transcript.")
                if st.button("🔄 Reanalyze Transcript", type="primary"):
                    with st.spinner("Reanalyzing..."):
                        try:
                            reanalyzed = backend.reanalyze(current_snapshot["job_id"], verify=True)
                            st.session_state.current_job_id = reanalyzed["job_id"]
                            st.success("Reanalysis complete!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Reanalysis failed: {e}")

    # ----------------------------------------------------
    # TAB 2: CLAIMS
    # ----------------------------------------------------
    with tab_claims:
        if not analysis:
            st.info("No claim analysis available. Please run or reanalyze this job.")
        else:
            claims = analysis.get("claims", [])
            st.markdown(f"### Claim Ledger ({len(claims)} Extracted Claims)")

            if not claims:
                st.caption("No factual claims were identified in this transcript.")
            else:
                # Filters
                f_col1, f_col2, f_col3 = st.columns(3)
                all_speakers = sorted(list({c.get("speaker_id", "") for c in claims}))
                all_subjects = sorted(list({c.get("subject") or "Unspecified" for c in claims}))
                all_checkability = ["All", "checkable", "needs_context"]

                with f_col1:
                    filter_speaker = st.selectbox("Filter by Speaker", ["All"] + all_speakers)
                with f_col2:
                    filter_subject = st.selectbox("Filter by Subject", ["All"] + all_subjects)
                with f_col3:
                    filter_check = st.selectbox("Filter by Checkability", all_checkability)

                filtered_claims = claims
                if filter_speaker != "All":
                    filtered_claims = [c for c in filtered_claims if c.get("speaker_id") == filter_speaker]
                if filter_subject != "All":
                    filtered_claims = [c for c in filtered_claims if (c.get("subject") or "Unspecified") == filter_subject]
                if filter_check != "All":
                    filtered_claims = [c for c in filtered_claims if c.get("checkability") == filter_check]

                st.caption(f"Showing {len(filtered_claims)} of {len(claims)} claims")

                # Claim display cards / table
                for c in filtered_claims:
                    c_id = c.get("claim_id")
                    sp_id = c.get("speaker_id")
                    sp_name = speakers_map.get(sp_id, sp_id) if "speakers_map" in locals() else sp_id
                    prop = c.get("proposition", "")
                    check_badge = "✅ checkable" if c.get("checkability") == "checkable" else "⚠️ needs_context"

                    with st.expander(f"**[{c_id}]** {sp_name}: {prop} ({check_badge})"):
                        col_det1, col_det2 = st.columns(2)
                        with col_det1:
                            st.markdown(f"**Speaker:** `{sp_id}` ({sp_name})")
                            st.markdown(f"**Subject:** {c.get('subject') or '—'}")
                            st.markdown(f"**Metric:** {c.get('metric') or '—'}")
                            st.markdown(f"**Time Period:** {c.get('period') or '—'}")
                            st.markdown(f"**Geography:** {c.get('geography') or '—'}")
                        with col_det2:
                            qty = c.get("quantity")
                            if qty:
                                st.markdown(f"**Normalized Value:** `{qty.get('value')}` {qty.get('unit', '')} ({qty.get('currency') or ''})")
                                st.markdown(f"**Raw Text:** *\"{qty.get('raw_text', '')}\"*")
                            else:
                                st.markdown("**Quantity:** None")

                            missing = c.get("missing_context", [])
                            if missing:
                                st.markdown(f"**Missing Context:** `{', '.join(missing)}`")

                        # Exact source quote
                        spans = c.get("source_spans", [])
                        if spans:
                            st.markdown("**Exact Transcript Quote:**")
                            for s in spans:
                                st.markdown(f"> *\"{s.get('quote')}\"* (Segment: `{s.get('segment_id')}`)")

    # ----------------------------------------------------
    # TAB 3: DISAGREEMENTS
    # ----------------------------------------------------
    with tab_disagreements:
        if not analysis:
            st.info("No disagreement analysis available.")
        else:
            pairs = analysis.get("pairs", [])
            claims_map = {c["claim_id"]: c for c in analysis.get("claims", [])}

            # Eligible conflicts: direct_conflict or numeric_discrepancy
            eligible_pairs = [p for p in pairs if p.get("relation") in ("direct_conflict", "numeric_discrepancy")]
            other_pairs = [p for p in pairs if p.get("relation") not in ("direct_conflict", "numeric_discrepancy")]

            # Sort eligible pairs by priority (1 is highest)
            eligible_pairs.sort(key=lambda p: (p.get("priority", 3), p.get("pair_id", "")))

            max_display = getattr(backend, "settings", {}).get("max_display_conflicts", 8)
            display_pairs = eligible_pairs[:max_display]

            st.markdown(f"### Disagreements ({len(eligible_pairs)} Eligible Conflict Pairs Found)")
            if len(eligible_pairs) > max_display:
                st.warning(f"Display capped at top {max_display} disagreements (out of {len(eligible_pairs)} total). All remain accessible in JSON export.")

            if not display_pairs:
                st.info("No direct conflicts or numeric discrepancies detected between speakers.")
            else:
                # Verification status lookup
                verified_pairs_map = {}
                if verification:
                    for r in verification.get("results", []):
                        verified_pairs_map[r["pair_id"]] = "Verified"
                    for u in verification.get("unverified", []):
                        verified_pairs_map[u["pair_id"]] = f"Unverified ({u.get('reason')})"

                selected_pair_ids = []

                for pair in display_pairs:
                    pid = pair["pair_id"]
                    ca_id = pair["claim_a_id"]
                    cb_id = pair["claim_b_id"]
                    ca = claims_map.get(ca_id, {})
                    cb = claims_map.get(cb_id, {})
                    relation = pair.get("relation")
                    v_state = verified_pairs_map.get(pid, "Not Checked")

                    # Border card
                    st.markdown(f"#### Disagreement `{pid}` — Priority {pair.get('priority')} | Relation: `{relation}`")
                    st.caption(f"Verification Status: **{v_state}**")

                    c_quote1, c_quote2 = st.columns(2)
                    with c_quote1:
                        st.markdown(f"**Claim A (`{ca_id}` — {ca.get('speaker_id')}):**")
                        st.info(f"\"{ca.get('proposition', '')}\"")
                    with c_quote2:
                        st.markdown(f"**Claim B (`{cb_id}` — {cb.get('speaker_id')}):**")
                        st.info(f"\"{cb.get('proposition', '')}\"")

                    st.markdown(f"**Explanation:** {pair.get('explanation')}")

                    diff = pair.get("numeric_difference")
                    unit = pair.get("numeric_difference_unit") or ""
                    if diff is not None:
                        st.markdown(f"**Computed Difference:** `{diff}` {unit}")

                    # Selection checkbox for verification
                    chk = st.checkbox(f"Select `{pid}` for Evidence Check", key=f"chk_{pid}")
                    if chk:
                        selected_pair_ids.append(pid)

                    st.divider()

                # Action buttons
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    st.caption(f"Selected {len(selected_pair_ids)} pairs (Maximum 4 per verification batch).")
                    if st.button("🔍 Check Selected Against Web Evidence", disabled=(len(selected_pair_ids) == 0 or len(selected_pair_ids) > 4)):
                        with st.spinner("Retrieving evidence and adjudicating..."):
                            def _verify_cb(msg: str):
                                st.toast(msg)

                            try:
                                updated_snap = backend.verify_pairs(
                                    current_snapshot["job_id"],
                                    selected_pair_ids,
                                    progress=_verify_cb,
                                )
                                st.session_state.current_job_id = updated_snap["job_id"]
                                st.success("Evidence check completed!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Verification failed: {e}")

                with col_btn2:
                    if hasattr(backend, "refresh_verification"):
                        if st.button("🔄 Refresh Evidence for Selected", disabled=(len(selected_pair_ids) == 0)):
                            with st.spinner("Invalidating cache and re-checking..."):
                                try:
                                    refreshed = backend.refresh_verification(
                                        current_snapshot["job_id"],
                                        selected_pair_ids,
                                    )
                                    st.session_state.current_job_id = refreshed["job_id"]
                                    st.success("Evidence refreshed!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Refresh failed: {e}")

            # Other candidate pairs expander
            if other_pairs:
                with st.expander(f"ℹ️ Other Assessed Pairs ({len(other_pairs)} Compatible / Different Scope)"):
                    st.caption("These pairs do not represent contradictions (e.g. different years or matching figures).")
                    for p in other_pairs:
                        st.markdown(
                            f"- **`{p['pair_id']}`** ({p.get('relation')}): Claims `{p['claim_a_id']}` vs `{p['claim_b_id']}`<br/>"
                            f"  *Explanation:* {p.get('explanation')}",
                            unsafe_allow_html=True,
                        )

    # ----------------------------------------------------
    # TAB 4: EVIDENCE & EXPORT
    # ----------------------------------------------------
    with tab_evidence:
        st.markdown("### 🔍 Retrieved Evidence & Claim Adjudication")

        if not verification or not verification.get("results"):
            st.info("No evidence verification has been run on this job yet. Use the Disagreements tab to select pairs to check.")
        else:
            evidence_by_id = {e["evidence_id"]: e for e in verification.get("evidence", [])}

            for result in verification.get("results", []):
                pid = result["pair_id"]
                st.markdown(f"#### Verdict for Disagreement `{pid}`")
                st.markdown(f"**Summary:** {result.get('summary')}")

                col_v1, col_v2 = st.columns(2)
                verdicts = result.get("verdicts", [])

                for idx, v in enumerate(verdicts):
                    col = col_v1 if idx == 0 else col_v2
                    with col:
                        cid = v["claim_id"]
                        status = v["status"]

                        # Wording strictly formatted per spec
                        if status == "supported":
                            status_display = "🟢 Supported by retrieved evidence"
                        elif status == "refuted":
                            status_display = "🔴 Refuted by retrieved evidence"
                        elif status == "insufficient_evidence":
                            status_display = "⚪ Insufficient evidence"
                        else:
                            status_display = "🟡 Needs context"

                        st.markdown(f"##### Claim `{cid}`: {status_display}")
                        st.markdown(f"**Rationale:** {v.get('rationale')}")

                        # Evidence references
                        refs = v.get("evidence_refs", [])
                        if refs:
                            st.markdown("**Citations:**")
                            for ref in refs:
                                ev_id = ref.get("evidence_id")
                                stance = ref.get("stance")
                                ev_item = evidence_by_id.get(ev_id)
                                if ev_item:
                                    st.markdown(f"- `{ev_id}` ({stance}): [{ev_item.get('title')}]({ev_item.get('url')})")

                # Show sources for this pair
                pair_evidences = [e for e in verification.get("evidence", []) if e.get("pair_id") == pid]
                if pair_evidences:
                    st.markdown("##### Retrieved Sources:")
                    for ev in pair_evidences:
                        origin = ev.get("content_origin")
                        if origin == "grounded_summary":
                            origin_badge = "Source-backed AI summary"
                        elif origin == "metadata_only":
                            origin_badge = "Source metadata only"
                        else:
                            origin_badge = "Synthetic evidence — demonstration only"

                        with st.expander(f"📄 {ev.get('title')} [{origin_badge}]"):
                            st.markdown(f"**URL:** [{ev.get('url')}]({ev.get('url')})")
                            st.markdown(f"**Origin:** `{origin_badge}` | **Retrieved At:** `{ev.get('retrieved_at')}`")
                            if ev.get("publisher"):
                                st.markdown(f"**Publisher:** {ev.get('publisher')}")
                            if ev.get("published_date"):
                                st.markdown(f"**Published Date:** {ev.get('published_date')}")
                            if ev.get("content"):
                                st.markdown(f"**Content / Excerpt:**\n> {ev.get('content')}")
                            else:
                                st.caption("No substantive excerpt available (Metadata only).")

                # Search entry point attribution (Google grounding requirement)
                attributions = [
                    a for a in verification.get("grounding_attributions", [])
                    if a.get("pair_id") == pid and a.get("search_entry_point_html")
                ]
                for attr in attributions:
                    st.markdown("**Google Search Entry Point:**")
                    # Isolated iframe rendering as mandated by provider
                    components.html(attr["search_entry_point_html"], height=60)

                st.divider()

        # Export section
        st.markdown("### 💾 Export Reports")
        st.caption("Snapshot JSON is complete and human-readable. Claims CSV includes formula-safe cells for Excel compatibility.")

        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            json_bytes = snapshot_json(current_snapshot)
            st.download_button(
                label="📥 Download Snapshot JSON",
                data=json_bytes,
                file_name=f"althea_snapshot_{current_snapshot.get('job_id', 'job')[:8]}.json",
                mime="application/json",
                use_container_width=True,
            )

        with col_exp2:
            csv_bytes = claims_csv(current_snapshot)
            st.download_button(
                label="📊 Download Claims CSV (Excel BOM)",
                data=csv_bytes,
                file_name=f"althea_claims_{current_snapshot.get('job_id', 'job')[:8]}.csv",
                mime="text/csv",
                use_container_width=True,
            )
