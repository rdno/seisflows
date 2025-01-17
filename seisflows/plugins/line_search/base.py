#!/usr/bin/env python3
"""
This is the Base class for seisflows.plugins.line_search

Line search is called on by the optimization procedure and should not really
have any agency (i.e. it should not be able to iterate its own step count etc.,
this should be completely left to the optimization algorithm to keep everything
in one place)
"""
import os
import logging
import numpy as np

from seisflows.tools.array import count_zeros


class Base:
    """
    Abstract base class for line search

    Variables Descriptions:
        x: list of step lenths from current line search
        f: correpsonding list of function values
        m: number of step lengths in current line search
        n: number of model updates in optimization problem
        gtg: dot product of gradient with itself
        gtp: dot product of gradient and search direction

    Status codes
        status > 0  : finished
        status == 0 : not finished
        status < 0  : failed
    """
    # Class-specific logger accessed using self.logger
    logger = logging.getLogger(__name__).getChild(__qualname__)

    def __init__(self, step_count_max, step_len_max, log_file):
        """

        :type step_count_max: int
        :param step_count_max: maximum number of step counts before changing
            line search behavior. set by PAR.STEP_COUNT_MAX
        :type step_len_max: int
        :param step_len_max: maximum length of the step, defaults to infinity,
            that is unbounded step length. set by PAR.STEP_LEN_MAX
        :type log_file: str
        :param log_file: path to write line search stats to. set by optimize.setup()
        """
        # Set maximum number of trial steps
        self.step_count_max = step_count_max

        # Optional maximum step length safeguard
        if step_len_max is None:
            self.step_len_max = np.inf
        else:
            self.step_len_max = step_len_max

        # Write header information to line search file
        self.log = log_file
        self.write_log()

        # Prepare lists for line search history
        self.func_vals = []
        self.step_lens = []
        self.gtg = []
        self.gtp = []
        self.step_count = 0

    def initialize(self, iter, step_len, func_val, gtg, gtp):
        """
        Initialize a new search from step count 0 and calculate the step
        direction and length

        :type iter: int
        :param iter: current iteration defined by OPTIMIZE.iter
        :type step_len: float
        :param step_len: initial step length determined by optimization
        :type func_val: float
        :param func_val: current evaluation of the objective function
        :type gtg: float
        :param gtg: dot product of the gradient with itself
        :type gtp: float
        :param gtp: dot product of gradient `g` with search direction `p`
        :rtype alpha: float
        :return alpha: the calculated trial step length
        :rtype status: int
        :return status: current status of the line search
        """
        self.step_count = 0
        self.step_lens += [step_len]
        self.func_vals += [func_val]
        self.gtg += [gtg]
        self.gtp += [gtp]

        # Write the current misfit evaluation to disk
        self.write_log(iter=iter, step_len=step_len, func_val=func_val)

        # Call calculate step, must be implemented by subclass
        alpha, status = self.calculate_step()

        return alpha, status

    def update(self, iter, step_len, func_val):
        """
        Update search history by appending internal attributes, writing the
        current list of step lengths and function evaluations, and calculating a
        new step length

        :type iter: int
        :param iter: current iteration defined by OPTIMIZE.iter
        :type step_len: float
        :param step_len: step length determined by optimization
        :type func_val: float
        :param func_val: current evaluation of the objective function
        :rtype alpha: float
        :return alpha: the calculated rial step length
        :rtype status: int
        :return status: current status of the line search
        """
        # This has been moved into workflow.line_search()
        # self.step_count += 1
        self.step_lens += [step_len]
        self.func_vals += [func_val]

        # Write the current misfit evaluation to disk
        self.write_log(iter=iter, step_len=step_len, func_val=func_val)

        # Call calcuate step, must be implemented by subclass
        alpha, status = self.calculate_step()

        return alpha, status

    def clear_history(self):
        """
        Clears internal line search history
        """
        self.func_vals = []
        self.step_lens = []
        self.gtg = []
        self.gtp = []
        self.step_count = 0

    def reset(self):
        """
        If a line search fails mid-search, and the User wants to resume from 
        the line search function. Initialize will be called again. This function
        undos the progress made by the previous line search so that a new line
        search can be called without problem.

        output.optim needs to have its lines cleared manually
        """
        # First step treated differently
        if len(self.step_lens) <= 1:
            self.clear_history()
        else:
            # Wind back dot products by one
            self.gtg = self.gtg[:-1]
            self.gtp = self.gtp[:-1]
            
            # Move step lens and function evaluations by number of step count
            original_idx = -1 * self.step_count - 1
            self.step_lens = self.step_lens[:original_idx]
            self.func_vals = self.func_vals[:original_idx]

    def write_log(self, iter=None, step_len=None, func_val=None):
        """
        Write the line search history into a formatted text file (self.log)
        that looks something like this:

            ITER     STEPLEN     MISFIT
        ========  ========== ==========
              1            0          1

        :type iter: int
        :param iter: the current iteration defined by OPTIMIZATION.iter.
        :type step_len: float
        :param step_len: Current step length of the line search, also known
            as 'alpha' in the optimization algorithm
        :type func_val: float
        :param func_val: the function evaluation, i.e., the misfit, associated
            with the given step length (alpha)
        """
        if (iter is None) or (not os.path.exists(self.log)):
            # Write out the header of the file to a NEW FILE
            self.logger.info(f"writing line search history file:\n{self.log}")
            with open(self.log, "w") as f:
                f.write(f"{'ITER':>10}  {'STEPLEN':>10}  {'MISFIT':>10}\n")
                f.write(f"{'='*10}  {'='*10}  {'='*10}\n")
        else:
            with open(self.log, "a") as f:
                # Aesthetic choice, don't repeat iteration numbers in the file
                if (step_len is not None) and (step_len > 0):
                    iter = ""
                f.write(f"{iter:>10}  {step_len:10.3e}  {func_val:10.3e}\n")

    def search_history(self, sort=True):
        """
        A convenience function, collects information based on the current
        evaluation of the line search, needed to determine search status and 
        calculate step length. From the full collection of the search history,
        only returns values relevant to the current line search.

        :type sort: bool
        :param sort: sort the search history by step length
        :rtype x: np.array
        :return x: list of step lenths from current line search
        :rtype f: np.array
        :return f: correpsonding list of function values
        :rtype gtg: list
        :return gtg: dot product dot product of gradient with itself
        :rtype gtp: list
        :return gtp: dot product of gradient and search direction
        :rtype i: int
        :return i: step_count
        :rtype j: int
        :return j: number of iterations corresponding to 0 step length
        """
        i = self.step_count
        j = count_zeros(self.step_lens) - 1
        k = len(self.step_lens)
        x = np.array(self.step_lens[k - i - 1:k])
        f = np.array(self.func_vals[k - i - 1:k])

        # Sort by step length
        if sort:
            f = f[abs(x).argsort()]
            x = x[abs(x).argsort()]

        return x, f, self.gtg, self.gtp, i, j

    def calculate_step(self):
        """
        Determines step length and search status

        !!! Must be implemented by subclass !!!
        """
        raise NotImplementedError("Must be implemented by subclass")


