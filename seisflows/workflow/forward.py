#!/usr/bin/env python3
"""
The simplest simulation workflow you can run is a large number of forward
simulations to generate synthetics from a velocity model. Therefore the
Forward class represents the BASE workflow. All other workflows will build off
of the scaffolding defined by the Forward class.
"""
import os
import sys
from glob import glob

from seisflows.core import Base
from seisflows.tools import msg
from seisflows.config import save


class Forward(Base):
    """
    Workflow abstract base class representing an en-masse forward solver and
    misfit calculator.
    """
    def __init__(self):
        """
        These parameters should not be set by the user.
        Attributes are initialized as NoneTypes for clarity and docstrings.
        """
        super().__init__()

        self.required.par(
            "SAVETRACES", required=False, default=False, par_type=bool,
            docstr="Save waveform traces to disk after they have been "
                   "generated by the external solver"
        )
        self.required.par(
            "SAVERESIDUALS", required=False, default=False, par_type=bool,
            docstr="Save data-synthetic residuals each time they are "
                   "caluclated"
        )
        self.required.path(
            "DATA", required=False, default=None,
            docstr="path to observed waveform data available to workflow"
        )
        self.required.path(
            "MODEL_INIT", required=False,
            default=os.path.join(self.path.WORKDIR, "specfem", "MODEL_INIT"),
            docstr="Path location of the initial model to be used to generate "
                   "the the first evaluation of synthetic seismograms."
        )
        self.required.path(
            "GRAD", required=False,
            default=os.path.join(self.path.WORKDIR, "scratch", "evalgrad"),
            docstr="scratch path to store data related to gradient evaluations"
        )

        # For keeping track of what functions to start and stop a workflow with
        self.start = None
        self.stop = None

    def check(self, validate=True):
        """
        Checks parameters and paths. Must be implemented by sub-class
        """
        super().check(validate=validate)

    def setup(self, flow=None, return_flow=False):
        """
        Setup workflow by intaking functions to be run and checking start and
        stop criteria
        """
        # REQUIRED: CLI command `seisflows print flow` needs this for output
        if return_flow:
            return flow

        # Allow User to start the workflow mid-FLOW, in the event that a
        # previous workflow errored, or if the User had previously stopped
        # a workflow to look at results and they want to pick up where
        # they left off
        self.start, self.stop = self._check_stop_resume_cond(flow)

        self.logger.info(
            msg.mjr(f"BEGINNING {self.__class__.__name__.upper()} WORKFLOW")
        )

        # Required modules that need to be set up
        self.logger.info(msg.mnr("PERFORMING MODULE SETUP"))
        self.module("system").setup()
        self.module("preprocess").setup()
        self.logger.info("setting up solver on system...")
        self.module("system").run("solver", "setup")

    def finalize(self):
        """
        Tasks related to tearing down a workflow
        """
        super().finalize()

        self.logger.info(
            msg.mjr(f"FINISHED {self.__class__.__name__} WORKFLOW")
        )

    def checkpoint(self):
        """
        Saves active SeisFlows working state to disk as Pickle files such that
        the workflow can be resumed following a crash, pause or termination of
        workflow.
        """
        save(path=self.path.OUTPUT)

    def main(self, flow=None, return_flow=False):
        """
        Execution of a workflow is equal to stsepping through workflow.main()

        An example main() script is provided below which details the requisite
        parts. This function will NOT execute as it is written in pseudocode.

        :type flow: list or tuple
        :param flow: list of Class methods that will be run in the order they
            are provided. If None, defaults to the evaluate_function() as
            defined by Forward class
        :type return_flow: bool
        :param return_flow: for CLI tool, simply returns the flow function
            rather than running the workflow. Used for print statements etc.
        """
        # The FLOW function defines a list of functions to execute IN ORDER
        if flow is None:
            flow = (self.evaluate_initial_misfit)

        self.setup(flow, return_flow)
        # Iterate through the `FLOW` to step through workflow.main()
        for func in flow[self.start: self.stop]:
            func()
        self.finalize()

    def evaluate_initial_misfit(self):
        """
        Wrapper for evaluate_function that generates synthetics via forward
        simulations, calculates misfits and sends residuals to PATH.GRAD and
        sets up the 'm_new' model for future evaluations
        """
        self.logger.info(msg.mjr("EVALUATING INITIAL MISFIT"))
        self._evaluate_function(path=self.path.GRAD, suffix="new")

    def _evaluate_function(self, path, suffix):
        """
        Performs forward simulation, and evaluates the objective function

        :type path: str
        :param path: path in the scratch directory to use for I/O
        :type suffix: str
        :param suffix: suffix to use for I/O
        """
        system = self.module("system")

        self.logger.info(msg.sub("EVALUATING OBJECTIVE FUNCTION"))

        model_tag = f"m_{suffix}"
        misfit_tag = f"f_{suffix}"

        self._write_model(path=path, model_tag=model_tag)

        self.logger.debug(f"evaluating objective function {self.par.NTASK} "
                          f"times on system...")
        system.run("solver", "eval_func", path=path)

        self._write_misfit(path=path, misfit_tag=misfit_tag)

    def _write_model(self, path, model_tag):
        """
        Writes model in format expected by solver

        :type path: str
        :param path: path to write the model to
        :type model_tag: str
        :param model_tag: name of the model to be saved, usually tagged as 'm' with
            a suffix depending on where in the inversion we are. e.g., 'm_try'.
            Expected that these tags are defined in OPTIMIZE module
        """
        solver = self.module("solver")
        optimize = self.module("optimize")

        dst = os.path.join(path, "model")
        self.logger.debug(f"saving model '{model_tag}' to:\n{dst}")
        solver.save(solver.split(optimize.load(model_tag)), dst)

    def _write_misfit(self, path, misfit_tag):
        """
        Writes misfit in format expected by nonlinear optimization library.
        Collects all misfit values within the given residuals directory and sums
        them in a manner chosen by the preprocess class.

        :type path: str
        :param path: path to write the misfit to
        :type misfit_tag: str
        :param misfit_tag: name of the model to be saved, usually tagged as
            'f' with a suffix depending on where in the inversion we are.
            e.g., 'f_try'. Expected that these tags are defined in OPTIMIZE
            module
        """
        preprocess = self.module("preprocess")
        optimize = self.module("optimize")

        self.logger.info("summing residuals with preprocess module")
        src = glob(os.path.join(path, "residuals", "*"))
        total_misfit = preprocess.sum_residuals(src)

        self.logger.debug(f"saving misfit {total_misfit:.3E} to '{misfit_tag}'")
        optimize.save(misfit_tag, total_misfit)

    def _check_stop_resume_cond(self, flow):
        """
        Chek the stop after and resume from conditions

        Allow the main() function to resume a workflow from a given flow
        argument, or stop the workflow after a given argument. In the event
        that a previous workflow errored, or if the User had previously
        stopped a workflow to look at results and they want to pick up where
        they left off.

        Late check: Exits the workflow if RESUME_FROM or STOP_AFTER arguments
        do not match any of the given flow arguments.

        :type flow: tuple of functions
        :param flow: an ordered list of functions that will be
        :rtype: tuple of int
        :return: (start, stop) indices of the `flow` input dictating where the
            list should be begun and ended. If RESUME_FROM and STOP_AFTER
            conditions are NOT given by the user, start and stop will be 0 and
            -1 respectively, meaning we should execute the ENTIRE list
        """
        fxnames = [func.__name__ for func in flow]

        # Default values which dictate that flow will execute in its entirety
        start_idx = None
        stop_idx = None

        # Overwrite start_idx if RESUME_FROM given, exit condition if no match
        if self.par.RESUME_FROM:
            try:
                start_idx = fxnames.index(self.par.RESUME_FROM)
                fx_name = flow[start_idx].__name__
                self.logger.info(
                    msg.mnr(f"WORKFLOW WILL RESUME FROM FUNC: '{fx_name}'")
                )
            except ValueError:
                self.logger.info(
                    msg.cli(f"{self.par.RESUME_FROM} does not correspond to any FLOW "
                            f"functions. Please check that self.par.RESUME_FROM "
                            f"matches one of the functions listed out in "
                            f"`seisflows print flow`.", header="error",
                            border="=")
                )
                sys.exit(-1)

        # Overwrite stop_idx if STOP_AFTER provided, exit condition if no match
        if self.par.STOP_AFTER:
            try:
                stop_idx = fxnames.index(self.par.STOP_AFTER)
                fx_name = flow[stop_idx].__name__
                stop_idx += 1  # increment to stop AFTER, due to python indexing
                self.logger.info(
                    msg.mnr(f"WORKFLOW WILL STOP AFTER FUNC: '{fx_name}'")
                )
            except ValueError:
                self.logger.info(
                    msg.cli(
                        f"{self.par.STOP_AFTER} does not correspond to any "
                        f"FLOW functions. Please check that PAR.STOP_AFTER "
                        f"matches one of the functions listed out in "
                        f"`seisflows print flow`.", header="error",
                        border="=")
                )
                sys.exit(-1)

        # Make sure stop after doesn't come before resume_from, otherwise none
        # of the flow will execute
        if self.par.STOP_AFTER and self.par.RESUME_FROM:
            if stop_idx <= start_idx:
                self.logger.info(
                    msg.cli(
                        f"PAR.STOP_AFTER=='{self.par.STOP_AFTER}' is called "
                        f"before PAR.RESUME_FROM=='{self.par.RESUME_FROM}' in "
                        f"the FLOW functions. Please adjust accordingly "
                        f"and rerun.", header="error", border="=")
                )
                sys.exit(-1)

        return start_idx, stop_idx

