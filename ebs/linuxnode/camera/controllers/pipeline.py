


class BlockingPipelineExecutor(object):
    # ----------------------------------------------------------------------
    # Generic pipeline executor
    # ----------------------------------------------------------------------
    def _execute_blocking_pipeline(
        self, cfg, pipeline,
        initial_context=None,
        report_progress=None,
        report_key=None,
        prefix="_pl_",
        special_steps=None,
    ):
        """
        Execute a pipeline of steps defined by the config object.

        Args:
            cfg: Configuration namespace (e.g., dict_to_ns(self._spec["config"]))
            pipeline (list[str]): Ordered step names.
            initial_context (dict): Initial context dict shared across steps.
            report_progress (callable): Called with {'max': N, 'done': i, 'current': step}.
            prefix (str): Prefix for step implementation methods (default '_pl_').
            special_steps (dict[str, callable]): Optional mapping of step_name -> custom spec generator.

        Returns:
            dict: The final context dict returned from the last step.
        """
        context = dict(initial_context or {})
        steps = len(pipeline)
        special_steps = special_steps or {}

        def get_step_spec(step_name):
            if step_name in special_steps:
                return special_steps[step_name](cfg)
            return getattr(cfg, step_name, None)

        def get_step_func(step_name, spec):
            if spec and hasattr(spec, "type"):
                func_name = spec.type
            else:
                func_name = step_name

            if not func_name:
                raise RuntimeError(f"Could not determine func_name for Step {step_name}")

            func_name = f"{prefix}{func_name}"
            try:
                return getattr(self, func_name)
            except AttributeError:
                raise RuntimeError(f"Function {func_name} for Step {step_name} not found")

        for idx, step in enumerate(pipeline):
            if report_progress:
                report_progress({'key': report_key, 'max': steps, 'done': idx, 'current': step})
            spec = get_step_spec(step)
            func = get_step_func(step, spec)
            context = func(spec, **context)

        if report_progress:
            report_progress({'key': report_key, 'max': steps, 'done': steps, 'current': 'done'})

        return context
