# All compute runs on the shared GPU box (docs/compute.md); the laptop edits, syncs and views.
#   make sync         laptop -> box copy ($(BOX):$(BOX_DIR))
#   make test         sync, then every suite on the box (scripts/box-test.sh)
#   make demo         sync, build the SYNTHETIC demo games through the worker on the box
#                     (cached: the second run is all cache hits), then serve API + TV web
#                     app + phone companion there (scripts/box-demo.sh)
#   make demo-tunnel  forward the demo ports to this machine (foreground; Ctrl-C to close)
#   make demo-stop    stop the demo servers on the box
#   make record-e2e   sync, record the automated end-to-end run on the box
#                     (scripts/record-e2e.sh), copy the MP4 to docs/evidence/E2E/
BOX ?= hfbox
BOX_DIR ?= /workspace/wt/replay-dev
DEMO_API_PORT ?= 8090
DEMO_TV_PORT ?= 5190
DEMO_WEB_PORT ?= 5191
SSH := ssh -o BatchMode=yes $(BOX)
RSYNC := rsync -az -e "ssh -o BatchMode=yes"
# /data/ is anchored: a bare "data/" would also drop apps/web/src/data.
SYNC_EXCLUDES := --exclude .git --exclude node_modules --exclude .venv \
	--exclude apps/web/test-results --exclude apps/web/playwright-report \
	--exclude /data/ --exclude samples/real --exclude infra/cdk.out \
	--exclude '/*.pt'
# ('/*.pt': YOLO weights ultralytics downloads into the copy on the box survive a sync)
DEMO_TMUX ?= replay-demo
DEMO_ENV := DEMO_API_PORT=$(DEMO_API_PORT) DEMO_TV_PORT=$(DEMO_TV_PORT) \
	DEMO_WEB_PORT=$(DEMO_WEB_PORT) DEMO_TMUX=$(DEMO_TMUX)

.PHONY: sync test demo demo-tunnel demo-stop record-e2e

sync:
	$(RSYNC) --delete $(SYNC_EXCLUDES) ./ $(BOX):$(BOX_DIR)/
	$(SSH) 'ln -sfn /workspace/wt/replay-env/samples-real $(BOX_DIR)/samples/real'

test: sync
	$(SSH) 'bash $(BOX_DIR)/scripts/box-test.sh $(BOX_DIR)'

# The build is nohup'd into a log on the box and followed here: a dropped ssh session (the
# cold build takes ~10 min) does not kill it, and a re-run waits for it, then hits the cache.
demo: sync
	$(SSH) 'log=$(BOX_DIR)/data/demo-build.log; mkdir -p $(BOX_DIR)/data && : > $$log; \
		nohup bash $(BOX_DIR)/scripts/box-demo.sh $(BOX_DIR) build >> $$log 2>&1 & p=$$!; \
		tail -n +1 -f --pid=$$p $$log; wait $$p'
	$(SSH) '$(DEMO_ENV) bash $(BOX_DIR)/scripts/box-demo.sh $(BOX_DIR) serve'
	@echo
	@echo "Demo is served on the box. View it here:"
	@echo "  make demo-tunnel    (keep it running)"
	@echo "  TV:    http://localhost:$(DEMO_TV_PORT)/        (arrow keys = D-pad, Enter = select, Esc = back)"
	@echo "  Phone: http://localhost:$(DEMO_WEB_PORT)/companion   (pair with the code the TV shows)"
	@echo "  make demo-stop      when done"

demo-tunnel:
	ssh -o BatchMode=yes -N -L $(DEMO_TV_PORT):127.0.0.1:$(DEMO_TV_PORT) \
		-L $(DEMO_WEB_PORT):127.0.0.1:$(DEMO_WEB_PORT) \
		-L $(DEMO_API_PORT):127.0.0.1:$(DEMO_API_PORT) $(BOX)

demo-stop:
	$(SSH) '$(DEMO_ENV) bash $(BOX_DIR)/scripts/box-demo.sh $(BOX_DIR) stop'

# The recorded end-to-end run (TV web build + phone companion, real API + worker, SYNTHETIC
# footage): scripts/record-e2e.sh on the box, then the <= 25 MB copy back here.
record-e2e: sync
	$(SSH) 'bash $(BOX_DIR)/scripts/record-e2e.sh $(BOX_DIR)'; \
	$(RSYNC) $(BOX):$(BOX_DIR)/out/replay-e2e.mp4 docs/evidence/E2E/
