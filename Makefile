# All compute runs on the shared GPU box (docs/compute.md); the laptop edits, syncs and views.
#   make sync   laptop -> box copy ($(BOX):$(BOX_DIR))
#   make test   sync, then every suite on the box (scripts/box-test.sh)
#   make demo   sync, process the synthetic sample through the worker on the box, pull the
#               processed game into ./data/games/, print how to view it locally
BOX ?= hfbox
BOX_DIR ?= /workspace/wt/replay-dev
DEMO_GAME ?= g_synth_basketball_half
SSH := ssh -o BatchMode=yes $(BOX)
RSYNC := rsync -az -e "ssh -o BatchMode=yes"
# /data/ is anchored: a bare "data/" would also drop apps/web/src/data.
SYNC_EXCLUDES := --exclude .git --exclude node_modules --exclude .venv \
	--exclude apps/web/test-results --exclude apps/web/playwright-report \
	--exclude /data/ --exclude samples/real --exclude infra/cdk.out \
	--exclude '/*.pt'
# ('/*.pt': YOLO weights ultralytics downloads into the copy on the box survive a sync)

.PHONY: sync test demo

sync:
	$(RSYNC) --delete $(SYNC_EXCLUDES) ./ $(BOX):$(BOX_DIR)/
	$(SSH) 'ln -sfn /workspace/wt/replay-env/samples-real $(BOX_DIR)/samples/real'

test: sync
	$(SSH) 'bash $(BOX_DIR)/scripts/box-test.sh $(BOX_DIR)'

demo: sync
	$(SSH) 'bash $(BOX_DIR)/scripts/box-demo.sh $(BOX_DIR) $(DEMO_GAME)'
	mkdir -p data/games
	$(RSYNC) --delete $(BOX):$(BOX_DIR)/data/games/$(DEMO_GAME)/ data/games/$(DEMO_GAME)/
	@echo
	@echo "Processed game is in data/games/$(DEMO_GAME). View it on this machine:"
	@echo "  REPLAY_PIPELINE=fake uv run --package replay-api uvicorn replay_api.main:app --port 8000"
	@echo "  cd apps/web && VITE_REPLAY_API_BASE=http://localhost:8000 pnpm exec vite --port 5173"
	@echo "  open http://localhost:5173/tv"
