.PHONY: preflight poc-check poc-summarize next-action

preflight:
	./run_flutter_poc_first_step.sh

poc-check:
	@if [ -z "$(FILES)" ]; then \
		echo 'Usage: make poc-check FILES="<ios-file.wav> <android-file.wav>"'; \
		exit 1; \
	fi
	./scripts/run_recorder_poc_check.sh $(FILES)

poc-summarize:
	@if [ -z "$(DIR)" ]; then \
		echo 'Usage: make poc-summarize DIR="verification/evidence/<timestamp>/recorder-poc"'; \
		exit 1; \
	fi
	./scripts/finalize_recorder_poc.sh $(DIR)

next-action:
	@cat NEXT_ACTION.md
