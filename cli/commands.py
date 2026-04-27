"""Command handler for CLI interface"""
import shlex
from typing import List, Optional
from .themes import theme
from jrvs.license import require_professional, LicenseError

class CommandHandler:
    def __init__(self, cli_instance):
        self.cli = cli_instance

    async def handle_command(self, command_line: str):
        """Parse and handle CLI commands"""
        try:
            args = shlex.split(command_line)
            if not args:
                return

            command = args[0].lower()
            command_args = args[1:] if len(args) > 1 else []

            # Route commands
            if command == "help":
                self.cli.show_help()
                
            elif command == "models":
                await self.cli.list_models()

            elif command == "model":
                if command_args:
                    await self.cli.switch_model(command_args[0])
                else:
                    await self.cli.list_models()

            elif command == "switch":
                if command_args:
                    await self.cli.switch_model(command_args[0])
                else:
                    theme.print_error("Usage: /switch <model_name>")
                    
            elif command == "screenshot":
                name = command_args[0] if command_args else None
                await self.cli.open_screenshot(name)

            elif command == "scrape":
                if command_args:
                    await self.cli.scrape_url(command_args[0])
                else:
                    theme.print_error("Usage: /scrape <url>")

            elif command == "code":
                if not command_args:
                    theme.print_error("Usage: /code <generate|analyze|explain|run|fix> ...")
                    theme.print_info("  /code generate <lang> <description>")
                    theme.print_info("  /code analyze  <filepath>")
                    theme.print_info("  /code explain  <filepath>")
                    theme.print_info("  /code run      <filepath>")
                    theme.print_info("  /code fix      <filepath> <error message>")
                elif command_args[0] == "generate":
                    if len(command_args) < 3:
                        theme.print_error("Usage: /code generate <language> <task description>")
                    else:
                        lang = command_args[1]
                        task = " ".join(command_args[2:])
                        await self.cli.jarcore_generate(lang, task)
                elif command_args[0] == "analyze":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /code analyze <filepath>")
                    else:
                        await self.cli.jarcore_analyze(command_args[1])
                elif command_args[0] == "explain":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /code explain <filepath>")
                    else:
                        await self.cli.jarcore_explain(command_args[1])
                elif command_args[0] == "run":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /code run <filepath>")
                    else:
                        await self.cli.jarcore_run(command_args[1])
                elif command_args[0] == "fix":
                    if len(command_args) < 3:
                        theme.print_error("Usage: /code fix <filepath> <error message>")
                    else:
                        filepath = command_args[1]
                        error_msg = " ".join(command_args[2:])
                        await self.cli.jarcore_fix(filepath, error_msg)
                else:
                    theme.print_error(f"Unknown code subcommand: {command_args[0]}")

            elif command == "websearch":
                if command_args:
                    query = " ".join(command_args)
                    await self.cli.websearch(query)
                else:
                    theme.print_error("Usage: /websearch <query>")
                    theme.print_info("Example: /websearch latest Python AI libraries")

            elif command == "brave-key":
                if command_args:
                    self.cli.set_brave_key(command_args[0])
                else:
                    theme.print_error("Usage: /brave-key <api_key>")

            elif command == "brave-status":
                self.cli.show_brave_status()

            elif command == "sources":
                self.cli.show_sources()
                    
            elif command == "search":
                if command_args:
                    query = " ".join(command_args)
                    await self.cli.websearch_and_answer(query)
                else:
                    theme.print_error("Usage: /search <query>")
                    theme.print_info("Example: /search is 2026 the worst year for layoffs due to AI?")

            elif command == "rag":
                if command_args:
                    query = " ".join(command_args)
                    await self.cli.search_documents(query)
                else:
                    theme.print_error("Usage: /rag <query>")
                    
            elif command == "stats":
                await self.cli.show_stats()
                
            elif command == "history":
                limit = 5
                if command_args and command_args[0].isdigit():
                    limit = int(command_args[0])
                await self.cli.show_conversation_history(limit)
                
            elif command == "theme":
                if command_args:
                    self.cli.set_theme(command_args[0])
                else:
                    theme.print_error("Usage: /theme <theme_name>")
                    theme.print_info("Available themes: matrix, cyberpunk, minimal")
                    
            elif command == "clear":
                theme.clear_screen()
                theme.print_banner()
                
            elif command == "calendar":
                await self.cli.show_calendar()

            elif command == "month":
                # /month or /month 11 2025
                month = None
                year = None
                if len(command_args) >= 1:
                    month = int(command_args[0])
                if len(command_args) >= 2:
                    year = int(command_args[1])
                await self.cli.show_month_calendar(month, year)

            elif command == "event":
                if len(command_args) >= 2:
                    await self.cli.add_event(command_args)
                else:
                    theme.print_error("Usage: /event <date> <time> <title>")
                    theme.print_info("Example: /event 2025-11-10 14:30 Team meeting")

            elif command == "today":
                await self.cli.show_today_events()

            elif command == "complete":
                if command_args and command_args[0].isdigit():
                    await self.cli.complete_event(int(command_args[0]))
                else:
                    theme.print_error("Usage: /complete <event_id>")

            elif command == "schedule":
                if not command_args:
                    await self.cli.list_schedules()
                elif command_args[0] == "log":
                    job_id = command_args[1] if len(command_args) > 1 else None
                    await self.cli.show_schedule_log(job_id)
                elif command_args[0] == "delete":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /schedule delete <id>")
                    else:
                        await self.cli.delete_schedule(command_args[1])
                else:
                    query = " ".join(command_args)
                    await self.cli.create_schedule(query)

            elif command == "approve":
                if command_args:
                    await self.cli.approve_schedule(command_args[0])
                else:
                    theme.print_error("Usage: /approve <schedule_id>")

            elif command == "deny":
                if command_args:
                    await self.cli.deny_schedule(command_args[0])
                else:
                    theme.print_error("Usage: /deny <schedule_id>")

            elif command == "mcp-servers":
                await self.cli.list_mcp_servers()

            elif command == "mcp-tools":
                server = command_args[0] if command_args else None
                await self.cli.list_mcp_tools(server)

            elif command == "mcp-call":
                if len(command_args) >= 3:
                    server = command_args[0]
                    tool = command_args[1]
                    args_json = " ".join(command_args[2:])
                    await self.cli.call_mcp_tool(server, tool, args_json)
                else:
                    theme.print_error("Usage: /mcp-call <server> <tool> <json_args>")
                    theme.print_info("Example: /mcp-call filesystem read_file '{\"path\": \"/tmp/test.txt\"}'")

            elif command == "report":
                self.cli.show_agent_report()

            elif command == "save-report":
                self.cli.save_agent_report()

            elif command == "google-auth":
                await self.cli.google_auth()

            elif command == "google-status":
                self.cli.google_status()

            elif command == "google-sync":
                await self.cli.google_sync()

            elif command == "google-pause":
                await self.cli.google_pause()

            elif command == "google-resume":
                await self.cli.google_resume()

            elif command == "gmail":
                if not command_args:
                    theme.print_error("Usage: /gmail search <query>  |  /gmail send <to> <subj> <body>")
                elif command_args[0] == "search":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /gmail search <query>")
                    else:
                        query = " ".join(command_args[1:])
                        await self.cli.gmail_search(query)
                elif command_args[0] == "send":
                    if len(command_args) < 4:
                        theme.print_error("Usage: /gmail send <to> <subject> <body>")
                    else:
                        to = command_args[1]
                        subject = command_args[2]
                        body = " ".join(command_args[3:])
                        await self.cli.gmail_send(to, subject, body)
                else:
                    theme.print_error(f"Unknown gmail subcommand: {command_args[0]}")

            elif command == "gdocs":
                if not command_args:
                    theme.print_error("Usage: /gdocs read <title|id>  |  /gdocs create <title> <content>")
                elif command_args[0] == "read":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /gdocs read <title or doc_id>")
                    else:
                        title_or_id = " ".join(command_args[1:])
                        await self.cli.gdocs_read(title_or_id)
                elif command_args[0] == "create":
                    if len(command_args) < 3:
                        theme.print_error("Usage: /gdocs create <title> <content>")
                    else:
                        title = command_args[1]
                        content = " ".join(command_args[2:])
                        await self.cli.gdocs_create(title, content)
                else:
                    theme.print_error(f"Unknown gdocs subcommand: {command_args[0]}")

            elif command == "gsheets":
                if not command_args:
                    theme.print_error("Usage: /gsheets read <id> [range]  |  /gsheets update <id> <range> <value>")
                elif command_args[0] == "read":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /gsheets read <title|id> [range]")
                    elif len(command_args) >= 3:
                        title_or_id = command_args[1]
                        range_ = command_args[2]
                        await self.cli.gsheets_read(title_or_id, range_)
                    else:
                        await self.cli.gsheets_read(command_args[1])
                elif command_args[0] == "update":
                    if len(command_args) < 4:
                        theme.print_error("Usage: /gsheets update <title|id> <range> <value>")
                    else:
                        title_or_id = command_args[1]
                        range_ = command_args[2]
                        value = " ".join(command_args[3:])
                        await self.cli.gsheets_update(title_or_id, range_, value)
                else:
                    theme.print_error(f"Unknown gsheets subcommand: {command_args[0]}")

            elif command == "upload":
                sub = command_args[0] if command_args else ""
                if sub == "list":
                    self.cli.upload_list()
                elif sub == "ingest":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /upload ingest <filename>")
                    else:
                        await self.cli.upload_ingest(command_args[1])
                elif sub == "ingest-all":
                    await self.cli.upload_ingest_all()
                elif sub == "read":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /upload read <filename>")
                    else:
                        self.cli.upload_read(command_args[1])
                else:
                    theme.print_error("Usage: /upload <list|read|ingest|ingest-all> [filename]")
                    theme.print_info("  /upload list               - List files in uploads/")
                    theme.print_info("  /upload read <file>        - Display file contents")
                    theme.print_info("  /upload ingest <file>      - Embed file into knowledge base")
                    theme.print_info("  /upload ingest-all         - Embed all supported files")

            elif command == "agent":
                sub = command_args[0] if command_args else ""
                if sub == "goals":
                    await self.cli.agent_list_goals()
                elif sub == "run":
                    if len(command_args) < 2:
                        theme.print_error("Usage: /agent run <goal_id>  |  /agent run --schedule <morning|hourly|daily|weekly>")
                    elif command_args[1] == "--schedule":
                        if len(command_args) < 3:
                            theme.print_error("Usage: /agent run --schedule <morning|hourly|daily|weekly>")
                        else:
                            await self.cli.agent_run_schedule(command_args[2])
                    else:
                        await self.cli.agent_run_goal(command_args[1])
                elif sub == "status":
                    self.cli.agent_scheduler_status()
                elif sub == "start":
                    try:
                        require_professional("Autonomous agent scheduler")
                    except LicenseError as exc:
                        theme.print_error(str(exc))
                        return
                    await self.cli.agent_start_scheduler()
                elif sub == "stop":
                    await self.cli.agent_stop_scheduler()
                else:
                    theme.print_error("Usage: /agent <goals|run|status|start|stop>")
                    theme.print_info("  /agent goals                          - List all goals from goals.yaml")
                    theme.print_info("  /agent run <id>                       - Run a specific goal now")
                    theme.print_info("  /agent run --schedule <morning|...>   - Run all goals for a schedule")
                    theme.print_info("  /agent status                         - Show scheduler state")
                    theme.print_info("  /agent start                          - Start the background scheduler")
                    theme.print_info("  /agent stop                           - Stop the background scheduler")

            elif command == "download":
                # Natural-language download confirmation (e.g. "go ahead and download them")
                # Delegates back to the LLM/MCP layer so the agent can call the ytdl tool
                # with the URLs it found in the previous turn.
                await self.cli.handle_chat_message(
                    "Use the ytdl MCP tool to download the tracks you just listed. "
                    "Call download_music() for each URL now."
                )

            elif command == "marketing":
                sub = command_args[0] if command_args else ""
                if sub == "queue":
                    # /marketing queue <brand> <platform> <topic...>
                    if len(command_args) < 4:
                        theme.print_error("Usage: /marketing queue <brand> <platform> <topic>")
                        theme.print_info("  Brands:    tensorlink, xthebuilder")
                        theme.print_info("  Platforms: linkedin, twitter, email")
                    else:
                        brand, platform = command_args[1], command_args[2]
                        topic = " ".join(command_args[3:])
                        try:
                            from marketing_module import marketing_module
                            job_id = await marketing_module.queue_draft(
                                brand=brand, platform=platform, topic=topic, source="cli"
                            )
                            theme.print_success(
                                f"Queued marketing draft {job_id[:8]} ({brand}/{platform})"
                            )
                            theme.print_info(
                                "Generation in progress — Slack notification when ready."
                            )
                        except ValueError as exc:
                            theme.print_error(str(exc))
                elif sub == "list":
                    brand = command_args[1] if len(command_args) > 1 else None
                    platform = command_args[2] if len(command_args) > 2 else None
                    try:
                        from marketing_module import marketing_module
                        drafts = await marketing_module.list_drafts(
                            brand=brand, platform=platform, limit=10
                        )
                        if not drafts:
                            theme.print_info("No drafts found.")
                        else:
                            for d in drafts:
                                limit = {"linkedin": 1300, "twitter": 280, "email": 0}.get(
                                    d["platform"], 0
                                )
                                count_note = (
                                    f"{d['char_count']}/{limit}"
                                    if limit else str(d["char_count"])
                                )
                                theme.print_info(
                                    f"#{d['id']:>4}  [{d['brand']}/{d['platform']}]"
                                    f"  {count_note} chars  {d['topic'][:60]}"
                                )
                    except Exception as exc:
                        theme.print_error(f"Error listing drafts: {exc}")
                else:
                    theme.print_error("Usage: /marketing <queue|list>")
                    theme.print_info("  /marketing queue <brand> <platform> <topic>")
                    theme.print_info("  /marketing list [brand] [platform]")

            elif command == "imagegen":
                sub = command_args[0] if command_args else ""

                if sub == "generate":
                    # Parse optional flags before the prompt
                    # Usage: /imagegen generate [--model X] [--steps N] [--cfg F] [--size WxH] <prompt...>
                    remaining = command_args[1:]
                    model, steps, cfg, width, height = "", 20, 7.0, 512, 512
                    prompt_parts = []
                    i = 0
                    while i < len(remaining):
                        tok = remaining[i]
                        if tok == "--model" and i + 1 < len(remaining):
                            model = remaining[i + 1]; i += 2
                        elif tok == "--steps" and i + 1 < len(remaining):
                            try: steps = int(remaining[i + 1])
                            except ValueError: theme.print_error("--steps must be an integer"); return
                            i += 2
                        elif tok == "--cfg" and i + 1 < len(remaining):
                            try: cfg = float(remaining[i + 1])
                            except ValueError: theme.print_error("--cfg must be a number"); return
                            i += 2
                        elif tok == "--size" and i + 1 < len(remaining):
                            try:
                                w, h = remaining[i + 1].lower().split("x")
                                width, height = int(w), int(h)
                            except (ValueError, AttributeError):
                                theme.print_error("--size must be WxH, e.g. 768x512"); return
                            i += 2
                        else:
                            prompt_parts.append(tok); i += 1

                    prompt = " ".join(prompt_parts).strip()
                    if not prompt:
                        theme.print_error("Usage: /imagegen generate [--model X] [--steps N] [--cfg F] [--size WxH] <prompt>")
                        return
                    try:
                        from image_gen_module import image_gen_module
                        job_id = await image_gen_module.queue_job(
                            prompt=prompt, model=model, steps=steps,
                            cfg=cfg, width=width, height=height, source="cli",
                        )
                        theme.print_success(f"Queued image job {job_id[:8]}")
                        theme.print_info(
                            f"  Prompt: {prompt[:80]}  |  {width}×{height}  "
                            f"steps={steps}  cfg={cfg}"
                            + (f"  model={model}" if model else "")
                        )
                        theme.print_info("Generation in progress — Slack notification when done.")
                    except ValueError as exc:
                        theme.print_error(str(exc))

                elif sub == "list":
                    status_filter = command_args[1] if len(command_args) > 1 else None
                    try:
                        from image_gen_module import image_gen_module
                        jobs = await image_gen_module.list_jobs(status=status_filter, limit=15)
                        if not jobs:
                            theme.print_info("No image jobs found.")
                        else:
                            for j in jobs:
                                path_note = j["output_path"] or "(pending)"
                                err_note  = f"  ERR: {j['error'][:60]}" if j.get("error") else ""
                                theme.print_info(
                                    f"#{j['id']:>4}  [{j['status']:<10}]  "
                                    f"{j['width']}×{j['height']}  "
                                    f"{j['prompt'][:50]}  →  {path_note}{err_note}"
                                )
                    except Exception as exc:
                        theme.print_error(f"Error listing jobs: {exc}")

                else:
                    theme.print_error("Usage: /imagegen <generate|list>")
                    theme.print_info("  /imagegen generate [--model X] [--steps N] [--cfg F] [--size WxH] <prompt>")
                    theme.print_info("  /imagegen list [queued|generating|done|failed]")

            elif command in ["exit", "quit", "bye"]:
                if theme.confirm("Are you sure you want to exit?"):
                    self.cli.running = False

            else:
                theme.print_error(f"Unknown command: /{command}")
                theme.print_info("Type '/help' for available commands")

        except Exception as e:
            theme.print_error(f"Command error: {e}")