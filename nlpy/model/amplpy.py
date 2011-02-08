"""
Python interface to the AMPL modeling language

.. moduleauthor:: M. P. Friedlander <mpf@cs.ubc.ca>
.. moduleauthor:: D. Orban <dominique.orban@gerad.ca>
"""

import numpy as np
from nlpy.model.nlp import NLPModel, KKTresidual
from nlpy.model import _amplpy as _amplpy
from nlpy.tools import sparse_vector_class as sv
from pysparse import spmatrix
import tempfile, os

__docformat__ = 'restructuredtext'

def Max(a):
    """
    A safeguarded max function. Returns -infinity for empty arrays.
    """
    if a.size > 0: return np.max(a)
    return -np.inf

def Min(a):
    """
    A safeguarded min function. Returns +infinity for empty arrays.
    """
    if a.size > 0: return np.min(a)
    return np.inf

########################################################################

def GenTemplate(model, data = None, opts = None):
    """
    Write out an Ampl template file,
    using files model.mod and data.dat (if available).
    The template will be given a temporary name.
    """

    # Create a temporary template file and write in a header.
    tmpname  = tempfile.mktemp()
    template = open(tmpname, 'w')
    template.write("# Template file for %s.\n" % model)
    template.write("# Automatically generated by AmplPy.\n")

    # Later we can use opts to hold a list of Ampl options, eg,
    #     option presolve 0;
    # that can be written into the template file.
    if opts is not None:
        pass

    # Template file body.
    if model[-4:] == '.mod': model = model[:-4]
    template.write("model %s.mod;\n"     % model)

    if data is not None:
        if data[-4:] == '.dat': data = data[:-4]
        template.write("data  %s.dat;\n" % data)
    template.write("write g%s;\n" % model)

    # Finish off the template file.
    template.close()

    # We'll need to know the template file name.
    return tmpname

########################################################################

def writestub(template):
    os.system("ampl %s" % template)

########################################################################

class AmplModel(NLPModel):
    """
    AmplModel creates an instance of an AMPL model. If the `nl` file is
    already available, simply call `AmplModel(stub)` where the string
    `stub` is the name of the model. For instance: `AmplModel('elec')`.
    If only the `.mod` file is available, set the positional parameter
    `neednl` to `True` so AMPL generates the `nl` file, as in
    `AmplModel('elec.mod', data='elec.dat', neednl=True)`.
    """

    def __init__(self, stub, **kwargs):

        data   = kwargs.get('data',   None)
        opts   = kwargs.get('opts',   None)

        if stub[-4:] == '.mod':
            # Create the nl file.
            template = GenTemplate(stub, data, opts)
            writestub(template)

        # Initialize the ampl module
        try:
            if stub[-4:] == '.mod': stub = stub[:-4]
            model = self.model = _amplpy.ampl(stub)
        except:
            raise ValueError, 'Cannot initialize model %s' % stub

        # Store problem name
        self.name = stub

        # Get basic info on problem
        self.minimize = (model.objtype == 0)
        self.n    = model.n_var
        self.m    = model.n_con
        self.x0   = model.get_x0()          # initial primal estimate
        self.pi0  = model.get_pi0()         # initial dual estimate
        self.Lvar = model.get_Lvar()        # lower bounds on variables
        self.Uvar = model.get_Uvar()        # upper bounds on variables
        self.Lcon = model.get_Lcon()        # lower bounds on constraints
        self.Ucon = model.get_Ucon()        # upper bounds on constraints
        (self.lin, self.nln, self.net) = model.get_CType() # Constraint types
        self.nlin = len(self.lin)           # number of linear    constraints
        self.nnln = len(self.nln)           #    ...    nonlinear   ...
        self.nnet = len(self.net)           #    ...    network     ...

        # Get sparsity info
        self.nnzj = model.get_nnzj()        # number of nonzeros in Jacobian
        self.nnzh = model.get_nnzh()        #                       Hessian

        # Initialize local value for Infinity
        self.Infinity = np.inf
        self.negInfinity = - np.inf

        # Maintain lists of indices for each type of constraints:
        self.rangeC = []    # Range constraints:       cL <= c(x) <= cU
        self.lowerC = []    # Lower bound constraints: cL <= c(x)
        self.upperC = []    # Upper bound constraints:       c(x) <= cU
        self.equalC = []    # Equality constraints:    cL  = c(x)  = cU
        self.freeC  = []    # "Free" constraints:    -inf <= c(x) <= inf

        for i in range(self.m):
            if self.Lcon[i] > self.negInfinity and self.Ucon[i] < self.Infinity:
                if self.Lcon[i] == self.Ucon[i]:
                    self.equalC.append(i)
                else:
                    self.rangeC.append(i)
            elif self.Lcon[i] > self.negInfinity:
                self.lowerC.append(i)
            elif self.Ucon[i] < self.Infinity:
                self.upperC.append(i)
            else:
                # Normally, we should not get here
                self.freeC.append(i)

        self.nlowerC = len(self.lowerC)
        self.nrangeC = len(self.rangeC)
        self.nupperC = len(self.upperC)
        self.nequalC = len(self.equalC)
        self.nfreeC  = len(self.freeC )

        self.permC = self.equalC + self.lowerC + self.upperC + self.rangeC

        # Proceed similarly with bound constraints
        self.rangeB = []
        self.lowerB = []
        self.upperB = []
        self.fixedB = []
        self.freeB  = []

        for i in range(self.n):
            if self.Lvar[i] > self.negInfinity and self.Uvar[i] < self.Infinity:
                if self.Lvar[i] == self.Uvar[i]:
                    self.fixedB.append(i)
                else:
                    self.rangeB.append(i)
            elif self.Lvar[i] > self.negInfinity:
                self.lowerB.append(i)
            elif self.Uvar[i] < self.Infinity:
                self.upperB.append(i)
            else:
                # This is a free variable
                self.freeB.append(i)

        self.nlowerB = len(self.lowerB)
        self.nrangeB = len(self.rangeB)
        self.nupperB = len(self.upperB)
        self.nfixedB = len(self.fixedB)
        self.nfreeB  = len(self.freeB)
        self.nbounds = self.n - self.nfreeB

        self.permB = self.fixedB + self.lowerB + self.upperB + \
            self.rangeB + self.freeB

        # Define default stopping tolerances
        self.stop_d = 1.0e-5    # Dual feasibility
        self.stop_c = 1.0e-5    # Complementarty
        self.stop_p = 1.0e-5    # Primal feasibility

        # Initializze scaling attributes
        self.scale_obj = None   # Objective scaling
        self.scale_con = None   # Constraint scaling

        # Set matrix format
        self.mformat = 0     # LL format
        if opts is not None:
            if opts == 0 or opts == 1:
                self.mformat = opts

        # Initialize some counters
        self.feval = 0    # evaluations of objective  function
        self.geval = 0    #                           gradient
        self.Heval = 0    #                Lagrangian Hessian
        self.Hprod = 0    #                matrix-vector products with Hessian
        self.ceval = 0    #                constraint functions
        self.Jeval = 0    #                           gradients
        self.Jprod = 0    #                matrix-vector products with Jacobian

    # Destructor
    def close(self):
        """Not needed anymore. Here for backward compatibility with
        original AmplPy interface."""
        pass

    def writesol(self, x, z, msg):
        """
        Write primal-dual solution and message msg to stub.sol
        """
        return self.model.ampl_sol(x, z, msg)

###############################################################################

    # Compute residuals of first-order optimality conditions

    def OptimalityResiduals(self, x, y, z, **kwargs):
        """
        Evaluate the KKT  or Fritz-John residuals at (x, y, z). The sign of the
        objective gradient is adjusted in this method as if the problem were a
        minimization problem.

        :parameters:

            :x:  Numpy array of length :attr:`n` giving the vector of
                 primal variables,

            :y:  Numpy array of length :attr:`m` + :attr:`nrangeC` giving the
                 vector of Lagrange multipliers for general constraints
                 (see below),

            :z:  Numpy array of length :attr:`nbounds` + :attr:`nrangeB` giving
                 the vector of Lagrange multipliers for simple bounds (see
                 below).

        :keywords:

            :c:  constraints vector, if known. Must be in appropriate order
                 (see below).

            :g:  objective gradient, if known.

            :J:  constraints Jacobian, if known. Must be in appropriate order
                 (see below).

        :returns:

            vectors of residuals
            (dual_feas, compl, bnd_compl, primal_feas, bnd_feas)

        The multipliers `y` associated to general constraints must be ordered
        as follows:

        :math:`c_i(x) = c_i^E`  (`i` in `equalC`): `y[:nequalC]`

        :math:`c_i(x) \geq c_i^L` (`i` in `lowerC`): `y[nequalC:nequalC+nlowerC]`

        :math:`c_i(x) \leq c_i^U` (`i` in `upperC`): `y[nequalC+nlowerC:nequalC+nlowerC+nupperC]`

        :math:`c_i(x) \geq c_i^L` (`i` in `rangeC`): `y[nlowerC+nupperC:m]`

        :math:`c_i(x) \leq c_i^U` (`i` in `rangeC`): `y[m:]`

        For inequality constraints, the sign of each `y[i]` should be as if it
        corresponded to a nonnegativity constraint, i.e.,
        :math:`c_i^U - c_i(x) \geq 0` instead of :math:`c_i(x) \leq c_i^U`.

        For equality constraints, the sign of each `y[i]` should be so the
        Lagrangian may be written::

            L(x,y,z) = f(x) - <y, c_E(x)> - ...

        Similarly, the multipliers `z` associated to bound constraints must be
        ordered as follows:

        1. `x_i  = L_i` (`i` in `fixedB`) : `z[:nfixedB]`

        2. `x_i \geq L_i` (`i` in `lowerB`) : `z[nfixedB:nfixedB+nlowerB]`

        3. `x_i \leq U_i` (`i` in `upperB`) : `z[nfixedB+nlowerB:nfixedB+nlowerB+nupperB]`

        4. `x_i \geq L_i` (`i` in `rangeB`) : `z[nfixedB+nlowerB+nupperB:nfixedB+nlowerB+nupperB+nrangeB]`

        5. `x_i \leq U_i` (`i` in `rangeB`) : `z[nfixedB+nlowerB+nupper+nrangeB:]`

        The sign of each `z[i]` should be as if it corresponded to a
        nonnegativity constraint (except for fixed variables), i.e., those
        `z[i]` should be nonnegative.

        It is possible to check the Fritz-John conditions via the keyword `FJ`.
        If `FJ` is present, it should be assigned the multiplier value that
        will be applied to the gradient of the objective function.

        Example: `OptimalityResiduals(x, y, z, FJ=1.0e-5)`

        If `FJ` has value `0.0`, the gradient of the objective will not be
        included in the residuals (it will not be computed).
        """

        # Make sure input multipliers have the right sign

        if self.m > 0:
            if len( np.where(y[self.nequalC:]<0)[0] ) > 0:
                raise ValueError, 'Negative Lagrange multipliers...'

        if self.nbounds > 0:
            if len( np.where(z[self.nfixedB:]<0)[0] ) > 0:
                raise ValueError, 'Negative Lagrange multipliers for bounds...'

        # Transfer some pointers for readability

        fixedB = self.fixedB ; nfixedB = self.nfixedB #; print fixedB
        lowerB = self.lowerB ; nlowerB = self.nlowerB #; print lowerB
        upperB = self.upperB ; nupperB = self.nupperB #; print upperB
        rangeB = self.rangeB ; nrangeB = self.nrangeB #; print rangeB
        Lvar = self.Lvar
        Uvar = self.Uvar

        zfixedB  = z[:nfixedB]
        zlowerB  = z[nfixedB:nfixedB+nlowerB]
        zupperB  = z[nfixedB+nlowerB:nfixedB+nlowerB+nupperB]
        zrangeBL = z[nfixedB+nlowerB+nupperB:nfixedB+nlowerB+nupperB+nrangeB]
        zrangeBU = z[nfixedB+nlowerB+nupperB+nrangeB:]

        equalC = self.equalC ; nequalC = self.nequalC #; print equalC
        lowerC = self.lowerC ; nlowerC = self.nlowerC #; print lowerC
        upperC = self.upperC ; nupperC = self.nupperC #; print upperC
        rangeC = self.rangeC ; nrangeC = self.nrangeC #; print rangeC
        Lcon = self.Lcon
        Ucon = self.Ucon

        # Partition vector of Lagrange multipliers

        yequalC  = y[:nequalC]
        ylowerC  = y[nequalC:nequalC+nlowerC]
        yupperC  = y[nequalC+nlowerC:nequalC+nlowerC+nupperC]
        yrangeCL = y[nequalC+nlowerC+nupperC:nequalC+nlowerC+nupperC+nrangeC]
        yrangeCU = y[nequalC+nlowerC+nupperC+nrangeC:]

        # Make sure input multipliers have the right sign

        if len( np.where(ylowerC < 0)[0] ) > 0:
            raise ValueError, 'Negative multipliers for lower constraints...'

        if len( np.where(yupperC < 0)[0] ) > 0:
            raise ValueError, 'Negative multipliers for upper constraints...'

        if len( np.where(yrangeCL < 0)[0] ) > 0:
            raise ValueError, 'Negative multipliers for range constraints...'

        if len( np.where(yrangeCU < 0)[0] ) > 0:
            raise ValueError, 'Negative multipliers for range constraints...'

        if self.nbounds > 0:
            if len( np.where(z[self.nfixedB:]<0)[0] ) > 0:
                raise ValueError, 'Negative multipliers for bounds...'

        # Bounds feasibility, part 1

        bRes = np.empty(nfixedB + nlowerB + nupperB + 2*nrangeB)
        n1 = nfixedB ; n2 = n1+nlowerB ; n3 = n2+nupperB; n4 = n3+nrangeB
        bRes[:n1]   = x[fixedB] - Lvar[fixedB]
        bRes[n1:n2] = x[lowerB] - Lvar[lowerB]
        bRes[n2:n3] = Uvar[upperB] - x[upperB]
        bRes[n3:n4] = x[rangeB] - Lvar[rangeB]
        bRes[n4:]   = Uvar[rangeB] - x[rangeB]

        # Complementarity of bound constraints

        bComp = bRes[n1:] * z[n1:]

        # Bounds feasibility, part 2

        bRes[n1:n2] = np.minimum(np.zeros(nlowerB), bRes[n1:n2])
        bRes[n2:n3] = np.minimum(np.zeros(nupperB), bRes[n2:n3])
        bRes[n3:n4] = np.minimum(np.zeros(nrangeB), bRes[n3:n4])
        bRes[n4:]   = np.minimum(np.zeros(nrangeB), bRes[n4:])

        # Initialize vector for primal feasibility

        pFeas = np.empty(self.m + nrangeC)
        if 'c' in kwargs:
            c = kwargs['c']
            pFeas[:self.m] = c.copy()
        else:
            pFeas[:self.m] = self.cons(x)[self.permC]
        pFeas[self.m:] = pFeas[rangeC]

        # Primal feasibility, part 1
        # Recall that self.cons() orders the constraints

        n1=nequalC ; n2=n1+nlowerC ; n3=n2+nupperC ; n4 = n3+nrangeC
        pFeas[:n1]   -= Lcon[equalC]
        pFeas[n1:n2] -= Lcon[lowerC]
        pFeas[n2:n3] -= Ucon[upperC] ; pFeas[n2:n3] *= -1  # Flip sign
        pFeas[n3:n4] -= Lcon[rangeC]
        pFeas[n4:]   -= Ucon[rangeC] ; pFeas[n4:]   *= -1  # Flip sign

        # Complementarity of general constraints

        gComp = pFeas[n1:] * y[n1:]

        # Primal feasibility, part 2

        pFeas[n1:n2] = np.minimum(np.zeros(nlowerC), pFeas[n1:n2])
        pFeas[n2:n3] = np.minimum(np.zeros(nupperC), pFeas[n2:n3])
        pFeas[n3:n4] = np.minimum(np.zeros(nrangeC), pFeas[n3:n4])
        pFeas[n4:]   = np.minimum(np.zeros(nrangeC), pFeas[n4:])

        # Build vector of Lagrange multipliers

        if nrangeC > 0:
            yloc = y[:n4].copy()
            yloc[n3:n4] -= y[n4:]
        else:
            yloc = y.copy()
        yloc[n2:n3] *= -1   # Flip sign for 'lower than' constraints

        # Dual feasibility

        if self.m > 0:
            dFeas = np.empty(self.n)
            J = kwargs.get('J', self.jac(x)[self.permC,:])
            J.matvec_transp(-yloc, dFeas)
        else:
            dFeas = np.zeros(self.n)
        dFeas[lowerB] -= zlowerB
        dFeas[upperB] += zupperB
        dFeas[rangeB] -= (zrangeBL - zrangeBU)

        # See if we are checking the Fritz-John conditions

        FJ = ('FJ' in kwargs.keys())
        objMult = kwargs.get('FJ', 1.0)

        if not FJ:
            g = kwargs.get('g', self.grad(x))
            if self.minimize:
                dFeas += g
            else:
                dFeas -= g   # Maximization problem.
        else:
            if float(objMult) != 0.0: dFeas += objMult * sign * self.grad(x)

        resids = KKTresidual(dFeas, pFeas, bRes, gComp, bComp)

        # Compute scalings.
        dScale = gScale = bScale = 1.0
        if self.m > 0:
            yNorm = np.linalg.norm(y, ord=1)
            dScale += yNorm /len(y)
        if self.m > nequalC:
            gScale += np.linalg.norm(y[lowerC + upperC + rangeC], ord=1)
            if nrangeC > 0:
                gScale += np.linalg.norm(y[self.m:], ord=1)
            gScale /= (nlowerC + nupperC + 2*nrangeC)
        if nlowerB + nupperB + nrangeB > 0:
            zNorm = np.linalg.norm(z, ord=1)
            bScale += zNorm /len(z)
            dScale += zNorm /len(z)

        scaling = KKTresidual(dScale, 1.0, 1.0, gScale, bScale)
        resids.set_scaling(scaling)
        return resids

    def AtOptimality(self, x, y, z, scale=True, **kwargs):
        """
        See :meth:`OptimalityResiduals` for a description of the arguments
        `x`, `y` and `z`. The additional `scale` argument decides whether
        or not residual scalings should be applied. By default, they are.

        :returns:

            :res:  `KKTresidual` instance, as returned by
                   :meth:`OptimalityResiduals`,
            :optimal:  `True` if the residuals fall below the thresholds
                       specified by :attr:`self.stop_d`, :attr:`self.stop_c`
                       and :attr:`self.stop_p`.
        """

        # Obtain optimality residuals
        res = self.OptimalityResiduals(x, y, z, **kwargs)

        df = np.linalg.norm(res.dFeas, ord=np.inf)
        if scale:
            df /= res.scaling.dFeas

        cp = fs = 0.0
        if self.m > 0:
            fs = np.linalg.norm(res.pFeas, ord=np.inf)
            if self.m > self.nequalC:
                cp = np.linalg.norm(res.gComp, ord=np.inf)
            if scale:
                cp /= res.scaling.gComp
                fs /= res.scaling.pFeas

        if self.nbounds > 0:
            bcp = np.linalg.norm(res.bComp, ord=np.inf)
            bfs = np.linalg.norm(res.bFeas, ord=np.inf)
            if scale:
                bcp /= res.scaling.bComp
                bfs /= res.scaling.bFeas
            cp = max(cp, bcp)
            fs = max(fs, bfs)

        #print 'KKT resids: ', (df, cp, fs)
        opt = (df<=self.stop_d) and (cp<=self.stop_c) and (fs<=self.stop_p)
        return (res, opt)

    def compute_scaling_obj(self, x=None, g_max=1.0e2, reset=False):
        """Compute objective scaling.

        :parameters:

            :x: Determine scaling by evaluating functions at this
                point. Default is to use :attr:`self.x0`.
            :g_max: Maximum allowed gradient. Default: :attr:`g_max = 1e2`.
            :reset: Set to `True` to unscale the problem.
        
        The procedure used here closely
        follows IPOPT's behavior; see Section 3.8 of

          Waecther and Biegler, 'On the implementation of an
          interior-point filter line-search algorithm for large-scale
          nonlinear programming', Math. Prog. A (106), pp.25-57, 2006

        which is a scalar rescaling that ensures the inf-norm of the
        gradient (at x) isn't larger than 'g_max'.

        """
        # Remove scaling if requested
        if reset:
            self.scale_obj = None
            self.pi0 = self.model.get_pi0() # get original multipliers
            return

        # Quick return if the problem is already scaled
        if self.scale_obj is not None:
            return

        if x is None: x = self.x0
        g = self.grad(x)
        gNorm = np.linalg.norm(g, np.inf)
        self.scale_obj = g_max / max(g_max, gNorm) # <= 1 always

        # Rescale the Lagrange multiplier
        self.pi0 *= self.scale_obj

    def compute_scaling_cons(self, x=None, g_max=1.0e2, reset=False):
        """
        Compute constraint scaling.
        
        :parameters:

            :x: Determine scaling by evaluating functions at this
                point. Default is to use :attr:`self.x0`.
            :g_max: Maximum allowed gradient. Default: :attr:`g_max = 1e2`.
            :reset: Set to `True` to unscale the problem.
        """
        # Remove scaling if requested
        if reset:
            self.scale_con = None
            self.Lcon = self.model.get_Lcon()        # lower bounds on constraints
            self.Ucon = self.model.get_Ucon()        # upper bounds on constraints
            return
        
        # Quick return if the problem is already scaled
        if self.scale_con is not None:
            return

        m = self.m
        if x is None: x = self.x0
        d_c = np.empty(m, dtype=np.double)
        J = self.jac(x)

        # Find inf-norm of each row of J
        for i in xrange(m):
            giNorm = J[i,:].norm('1') # This is the matrix 1-norm (max abs col)
            d_c[i] = g_max / max(g_max, giNorm) # <= 1 always
        self.scale_con = d_c

        # Scale constraint bounds
        self.Lcon *= d_c        # lower bounds on constraints
        self.Ucon *= d_c        # upper bounds on constraints

        # Form a diagonal matrix from scales; useful for scaling Jacobian
        D_c = spmatrix.ll_mat_sym(m, m)
        D_c.put(d_c, range(m))
        self.scale_con_diag = D_c


###############################################################################

    # The following methods mirror the module functions defined in _amplpy.c.

    def obj(self, x):
        """
        Evaluate objective function value at x.
        Returns a floating-point number. This method changes the sign of the
        objective value if the problem is a maximization problem.
        """
        f = self.model.eval_obj(x)
        self.feval += 1
        if self.scale_obj:    f *= self.scale_obj
        if not self.minimize: f *= -1
        return f


    def grad(self, x):
        """
        Evaluate objective gradient at x.
        Returns a Numpy array. This method changes the sign of the objective
        gradient if the problem is a maximization problem.
        """
        g = self.model.grad_obj(x)
        self.geval += 1
        if self.scale_obj:    g *= self.scale_obj
        if not self.minimize: g *= -1
        return g


    def sgrad(self, x):
        """
        Evaluate sparse objective gradient at x.
        Returns a sparse vector. This method changes the sign of the objective
        gradient if the problem is a maximization problem.
        """
        try:
            sg_dict = self.model.eval_sgrad(x)
        except:
            raise RuntimeError, "Failed to fetch sparse gradient of objective"
            return None
        self.geval += 1
        sg = sv.SparseVector(self.n, sg_dict)
        if self.scale_obj:    sg *= self.scale_obj
        if not self.minimize: sg *= -1
        return sg


    def cost(self):
        """
        Evaluate sparse cost vector.
        Useful when problem is a linear program.
        Return a sparse vector. This method changes the sign of the cost vector
        if the problem is a maximization problem.
        """
        try:
            sc_dict = self.model.eval_cost()
        except:
            raise RuntimeError, "Failed to fetch sparse cost vector"
            return None
        sc = sv.SparseVector(self.n, sc_dict)
        if self.scale_obj:    sc *= self.scale_obj
        if not self.minimize: sc *= -1
        return sc


    def cons(self, x):
        """
        Evaluate vector of constraints at x.
        Returns a Numpy array.

        The constraints appear in natural order. To order them as follows

        1) equalities

        2) lower bound only

        3) upper bound only

        4) range constraints,

        use the `permC` permutation vector.
        """
        try:
            c = self.model.eval_cons(x)
        except:
            print ' Offending argument : '
            for i in range(self.n):
                print '%-15.9f ' % x[i]
            return None #c = self.Infinity * np.ones(self.m)
        self.ceval += 1
        if self.scale_con is not None: c *= self.scale_con # componentwise product
        return c #[self.permC]


    def consPos(self, x):
        """
        Convenience function to return the vector of constraints
        reformulated as

            ci(x) - ai  = 0  for i in equalC
            ci(x) - Li >= 0  for i in lowerC + rangeC
            Ui - ci(x) >= 0  for i in upperC + rangeC.

        The constraints appear in natural order, except for the fact that the
        'upper side' of range constraints is appended to the list.

        No need to apply scaling, since this is already done in cons().
        """
        m = self.m
        equalC = self.equalC
        lowerC = self.lowerC
        upperC = self.upperC
        rangeC = self.rangeC ; nrangeC = self.nrangeC

        c = np.empty(m + nrangeC)
        c[:m] = self.cons(x)
        c[m:] = c[rangeC]

        c[equalC] -= self.Lcon[equalC]
        c[lowerC] -= self.Lcon[lowerC]
        c[upperC] -= self.Ucon[upperC] ; c[upperC] *= -1
        c[rangeC] -= self.Lcon[rangeC]
        c[m:]     -= self.Ucon[rangeC] ; c[m:] *= -1

        return c


    def icons(self, i, x):
        """
        Evaluate value of i-th constraint at x.
        Returns a floating-point number.
        """
        self.ceval += 1
        ci = self.model.eval_ci(i, x)
        if self.scale_con is not None: ci *= self.scale_con[i]
        return ci


    def igrad(self, i, x):
        """
        Evaluate dense gradient of i-th constraint at x.
        Returns a Numpy array.
        """
        self.Jeval += 1
        gi = self.model.eval_gi(i, x)
        if self.scale_con is not None: gi *= self.scale_con[i]
        return gi


    def sigrad(self, i, x):
        """
        Evaluate sparse gradient of i-th constraint at x.
        Returns a sparse vector representing the sparse gradient
        in coordinate format.
        """
        try:
            sci_dict = self.model.eval_sgi(i, x)
        except:
            raise RuntimeError, "Failed to fetch sparse constraint gradient"
            return None
        self.Jeval += 1
        sci = sv.SparseVector(self.n, sci_dict)
        if self.scale_con is not None: sci *= self.scale_con[i]
        return sci


    def irow(self, i):
        """
        Evaluate sparse gradient of the linear part of the
        i-th constraint. Useful to obtain constraint rows
        when problem is a linear programming problem.
        """
        try:
            sri_dict = self.model.eval_row(i)
        except:
            raise RuntimeError, "Failed to fetch sparse row"
            return None
        sri = sv.SparseVector(self.n, sri_dict)
        if self.scale_con is not None: sri *= self.scale_con[i]
        return sri


    def A(self, *args, **kwargs):
        """
        Evaluate sparse Jacobian of the linear part of the
        constraints. Useful to obtain constraint matrix
        when problem is a linear programming problem.
        """
        store_zeros = kwargs.get('store_zeros', False)
        store_zeros = 1 if store_zeros else 0
        if len(args) == 1:
            if type(args[0]).__name__ == 'll_mat':
                Amat = self.model.eval_A(store_zeros,args[0])
            else:
                return None
        else:
            Amat = self.model.eval_A(store_zeros)

        if self.scale_con is not None:
            Amat = spmatrix.matrixmultiply(Amat, self.scale_con_diag)
        return Amat


    def jac(self, x, *args, **kwargs):
        """
        Evaluate sparse Jacobian of constraints at x.
        Returns a sparse matrix in format self.mformat
        (0 = compressed sparse row, 1 = linked list).

        The constraints appear in the following order:

        1. equalities
        2. lower bound only
        3. upper bound only
        4. range constraints.
        """
        store_zeros = kwargs.get('store_zeros', False)
        store_zeros = 1 if store_zeros else 0
        if len(args) > 0:
            if type(args[0]).__name__ == 'll_mat':
                J = self.model.eval_J(x, self.mformat, store_zeros, args[0])
            else:
                return None
        else:
            J = self.model.eval_J(x, self.mformat, store_zeros)
        self.Jeval += 1

        # Warning!! This next line doesn't work for the coordinate format option.
        if self.scale_con is not None:
            J = spmatrix.matrixmultiply(self.scale_con_diag, J)
        return J #[self.permC,:]


    def jacPos(self, x, **kwargs):
        """
        Convenience function to evaluate the Jacobian matrix of the constraints
        reformulated as

            ci(x) = ai       for i in equalC

            ci(x) - Li >= 0  for i in lowerC

            ci(x) - Li >= 0  for i in rangeC

            Ui - ci(x) >= 0  for i in upperC

            Ui - ci(x) >= 0  for i in rangeC.

        The gradients of the general constraints appear in
        'natural' order, i.e., in the order in which they appear in the problem.
        The gradients of range constraints appear in two places: first in the
        'natural' location and again after all other general constraints, with a
        flipped sign to account for the upper bound on those constraints.

        The overall Jacobian of the new constraints thus has the form

        [ J ]
        [-JR]

        This is a `m + nrangeC` by `n` matrix, where `J` is the Jacobian of the
        general constraints in the order above in which the sign of the 'less
        than' constraints is flipped, and `JR` is the Jacobian of the 'less
        than' side of range constraints.
        """
        store_zeros = kwargs.get('store_zeros', False)
        store_zeros = 1 if store_zeros else 0
        n = self.n ; m = self.m ; nrangeC = self.nrangeC
        upperC = self.upperC ; rangeC = self.rangeC

        # Initialize sparse Jacobian
        J = sp(nrow=m + nrangeC, ncol=n, sizeHint=self.nnzj+10*nrangeC,
               storeZeros=store_zeros)

        # Insert contribution of general constraints
        J[:m,:n] = self.jac(x, store_zeros=store_zeros) #[self.permC,:]
        J[upperC,:n] *= -1                 # Flip sign of 'upper' gradients
        J[m:,:n] = -J[rangeC,:n]           # Append 'upper' side of range const.
        return J


    def hess(self, x, z, *args, **kwargs):
        """
        Evaluate sparse lower triangular Hessian at (x, z).
        Returns a sparse matrix in format self.mformat
        (0 = compressed sparse row, 1 = linked list).

        Note that the sign of the Hessian matrix of the objective function
        appears as if the problem were a minimization problem.
        """
        obj_weight = kwargs.get('obj_weight', 1.0)
        store_zeros = kwargs.get('store_zeros', False)
        store_zeros = 1 if store_zeros else 0
        if len(args) > 0:
            if type(args[0]).__name__ == 'll_mat':
                H = self.model.eval_H(x, z, self.mformat, obj_weight, args[0],
                                      store_zeros)
            else:
                return None
        else:
            H = self.model.eval_H(x, z, self.mformat, obj_weight, store_zeros)
        self.Heval += 1

        if self.scale_obj:
            if self.mformat == 0: # compressed sparse
                H[0] *= self.scale_obj
            else:
                H *= self.scale_obj
        return H


    def hprod(self, z, v, **kwargs):
        """
        Evaluate matrix-vector product H(x,z) * v.
        Returns a Numpy array.

        :keywords:
            :obj_weight: Add a weight to the Hessian of the objective function.
                         By default, the weight is one. Setting it to zero
                         allows to exclude the Hessian of the objective from
                         the Hessian of the Lagrangian.

        Note that the sign of the Hessian matrix of the objective function
        appears as if the problem were a minimization problem.
        """
        obj_weight = kwargs.get('obj_weight', 1.0)
        self.Hprod += 1
        Hv = self.model.H_prod(z, v, obj_weight)
        if self.scale_obj:
            Hv *= self.scale_obj
        return Hv
    

    def hiprod(self, i, v, **kwargs):
        """
        Evaluate matrix-vector product Hi(x) * v.
        Returns a Numpy array.
        """
        z = np.zeros(self.m) ; z[i] = -1
        self.Hprod += 1
        Hv = self.model.H_prod(z, v, 0.)
        if self.scale_con is not None:
            Hv *= self.scale_con[i]
        return Hv
    

    def ghivprod(self, g, v, **kwargs):
        """
        Evaluate the vector of dot products (g, Hi*v) where Hi is the Hessian
        of the i-th constraint, i=1..m.
        """
        if self.nnln == 0:           # Quick exit if no nonlinear constraints
            return np.zeros(self.m)
        self.Hprod += self.nnln      # Count all Hprods needed for this call
        gHi = self.model.gHi_prod(g, v)
        if self.scale_con is not None:
            gHi *= self.scale_con    # componentwise product
        return gHi
    

    def islp(self):
        """
        Determines whether problem is a linear programming problem.
        """
        if self.nlo or self.nlc or self.nlnc:
            return True
        else:
            return False


    def set_x(self,x):
        """
        Set `x` as current value for subsequent calls
        to :meth:`obj`, :meth:`grad`, :meth:`jac`, etc. If several
        of :meth:`obj`, :meth:`grad`, :meth:`jac`, ..., will be called with the
        same argument `x`, it may be more efficient to first call `set_x(x)`.
        In AMPL, :meth:`obj`, :meth:`grad`, etc., normally check whether their
        argument has changed since the last call. Calling `set_x()` skips this
        check.

        See also :meth:`unset_x`.
        """
        return self.model.set_x(x)


    def unset_x(self):
        """
        Reinstates the default behavior of :meth:`obj`, :meth:`grad`, `jac`,
        etc., which is to check whether their argument has changed since the
        last call.

        See also :meth:`set_x`.
        """
        return self.model.unset_x()


    def display_basic_info(self):
        """
        Display vital statistics about the current model.
        """
        import sys
        write = sys.stderr.write
        write('Problem Name: %s\n' % self.name)
        write('Number of Variables: %d\n' % self.n)
        write('Number of Bound Constraints: %d' % self.nbounds)
        write(' (%d lower, %d upper, %d two-sided)\n' % (self.nlowerB,
            self.nupperB, self.nrangeB))
        if self.nlowerB > 0: write('Lower bounds: %s\n' % self.lowerB)
        if self.nupperB > 0: write('Upper bounds: %s\n' % self.upperB)
        if self.nrangeB > 0: write('Two-Sided bounds: %s\n' % self.rangeB)
        write('Vector of lower bounds: %s\n' % self.Lvar)
        write('Vectof of upper bounds: %s\n' % self.Uvar)
        write('Number of General Constraints: %d' % self.m)
        write(' (%d equality, %d lower, %d upper, %d range)\n' % (self.nequalC,
            self.nlowerC, self.nupperC, self.nrangeC))
        if self.nequalC > 0: write('Equality: %s\n' % self.equalC)
        if self.nlowerC > 0: write('Lower   : %s\n' % self.lowerC)
        if self.nupperC > 0: write('Upper   : %s\n' % self.upperC)
        if self.nrangeC > 0: write('Range   : %s\n' % self.rangeC)
        write('Vector of constraint lower bounds: %s\n' % self.Lcon)
        write('Vector of constraint upper bounds: %s\n' % self.Ucon)
        write('Number of Linear Constraints: %d\n' % self.nlin)
        write('Number of Nonlinear Constraints: %d\n' % self.nnln)
        write('Number of Network Constraints: %d\n' % self.nnet)
        write('Number of nonzeros in Jacobian: %d\n' % self.nnzj)
        write('Number of nonzeros in Lagrangian Hessian: %d\n' % self.nnzh)
        if self.islp(): write('This problem is a linear program.\n')
        write('Initial Guess: %s\n' % self.x0)

        return


###############################################################################
