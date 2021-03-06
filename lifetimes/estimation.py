from __future__ import print_function
from collections import OrderedDict
import math
import numpy as np
from numpy import log, exp, logaddexp, asarray, any as npany, c_ as vconcat, \
    isinf, isnan, ones_like
from pandas import DataFrame
from scipy import special
from scipy import misc
from lifetimes.utils import _fit, _scale_time, _check_inputs, customer_lifetime_value, ncr
from lifetimes.generate_data import pareto_nbd_model, beta_geometric_nbd_model, modified_beta_geometric_nbd_model, \
    bgbb_model, bgbbbg_model, bgbbbgext_model, bgext_model
from lifetimes.formulas import gamma_ratio
from functools import reduce
__all__ = ['BetaGeoFitter', 'ParetoNBDFitter', 'GammaGammaFitter', 'ModifiedBetaGeoFitter']

B = special.beta


class BaseFitter(object):

    params_ = None
    data = None

    def __repr__(self):
        classname = self.__class__.__name__
        try:
            s = """<lifetimes.%s: fitted with %d subjects, %s>""" % (
                classname, self.data.shape[0], self._print_params())
        except AttributeError:
            s = """<lifetimes.%s>""" % classname
        return s

    def _unload_params(self, *args):
        if not hasattr(self, 'params_'):
            raise ValueError("Model has not been fit yet. Please call the .fit method first.")
        return [self.params_[x] for x in args]

    def _print_params(self):
        s = ""
        for p, value in self.params_.items():
            s += "%s: %.2f, " % (p, value)
        return s.strip(', ')


class GammaGammaFitter(BaseFitter):
    def __init__(self, penalizer_coef=0.):
        self.penalizer_coef = penalizer_coef

    @staticmethod
    def _negative_log_likelihood(params, frequency, avg_monetary_value, penalizer_coef=0):
        if any(i < 0 for i in params):
            return np.inf

        p, q, v = params

        x = frequency
        m = avg_monetary_value

        negative_log_likelihood_values = special.gammaln(p * x + q) - special.gammaln(p * x) - special.gammaln(q) \
                                         + q * np.log(v) + (p * x - 1) * np.log(m) + (p * x) * np.log(x) - (
                                                                                                               p * x + q) * np.log(
            x * m + v)

        penalizer_term = penalizer_coef * log(params).sum()
        negative_log_likelihood = -np.sum(negative_log_likelihood_values) + penalizer_term

        return negative_log_likelihood

    def conditional_expected_average_profit(self, frequency=None, monetary_value=None):
        """
        This method computes the conditional expectation of the average profit per transaction
        for a group of one or more customers.
            x: a vector containing the customers' frequencies. Defaults to the whole set of
                frequencies used for fitting the model.
            m: a vector containing the customers' monetary values. Defaults to the whole set of
                monetary values used for fitting the model.

        Returns:
            the conditional expectation of the average profit per transaction
        """
        m = self.data['monetary_value'] if monetary_value is None else monetary_value
        x = self.data['frequency'] if frequency is None else frequency
        p, q, v = self._unload_params('p', 'q', 'v')
        return (((q - 1) / (p * x + q - 1)) * (v * p / (q - 1))) + (p * x / (p * x + q - 1)) * m

    def fit(self, frequency, monetary_value, iterative_fitting=5, initial_params=None, verbose=False, N=None):
        """
        This methods fits the data to the Gamma/Gamma model.

        Parameters:
            N:
            frequency: the frequency vector of customers' purchases (denoted x in literature).
            monetary_value: the monetary value vector of customer's purchases (denoted m in literature).
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates. This model is not very stable so we suggest >10 for best estimates evaluation.
            initial_params: set initial params for the iterative fitter.
            verbose: set to true to print out convergence diagnostics.

        Returns:
            self, fitted and with parameters estimated
        """
        params, self._negative_log_likelihood_ = _fit(self._negative_log_likelihood,
                                                      [frequency, monetary_value, self.penalizer_coef],
                                                      iterative_fitting,
                                                      initial_params,
                                                      3,
                                                      verbose)

        self.data = DataFrame(vconcat[frequency, monetary_value], columns=['frequency', 'monetary_value'])
        self.params_ = OrderedDict(zip(['p', 'q', 'v'], params))

        return self

    def customer_lifetime_value(self, transaction_prediction_model, frequency, recency, T, monetary_value, time=12,
                                discount_rate=1):
        """
        This method computes the average lifetime value for a group of one or more customers.
            transaction_prediction_model: the model to predict future transactions, literature uses
                pareto/ndb but we can also use a different model like bg
            frequency: the frequency vector of customers' purchases (denoted x in literature).
            recency: the recency vector of customers' purchases (denoted t_x in literature).
            T: the vector of customers' age (time since first purchase)
            monetary_value: the monetary value vector of customer's purchases (denoted m in literature).
            time: the lifetime expected for the user in months. Default: 12
            discount_rate: the monthly adjusted discount rate. Default: 1

        Returns:
            Series object with customer ids as index and the estimated customer lifetime values as values
        """
        adjusted_monetary_value = self.conditional_expected_average_profit(frequency,
                                                                           monetary_value)  # use the Gamma-Gamma estimates for the monetary_values
        return customer_lifetime_value(transaction_prediction_model, frequency, recency, T, adjusted_monetary_value,
                                       time, discount_rate)


class ParetoNBDFitter(BaseFitter):
    def __init__(self, penalizer_coef=0.):
        self.penalizer_coef = penalizer_coef

    def fit(self, frequency, recency, T, iterative_fitting=0, initial_params=None, verbose=False, N=None):
        """
        This methods fits the data to the Pareto/NBD model.

        Parameters:
            frequency: the frequency vector of customers' purchases (denoted x in literature).
            recency: the recency vector of customers' purchases (denoted t_x in literature).
            T: the vector of customers' age (time since first purchase)
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates.
            initial_params: set initial params for the iterative fitter.
            verbose: set to true to print out convergence diagnostics.

        Returns:
            self, with additional properties and methods like params_ and plot

        """
        frequency = asarray(frequency)
        recency = asarray(recency)
        T = asarray(T)
        _check_inputs(frequency, recency, T)

        params, self._negative_log_likelihood_ = _fit(self._negative_log_likelihood,
                                                      [frequency, recency, T, self.penalizer_coef],
                                                      iterative_fitting,
                                                      initial_params,
                                                      4,
                                                      verbose)

        self.params_ = OrderedDict(zip(['r', 'alpha', 's', 'beta'], params))
        self.data = DataFrame(vconcat[frequency, recency, T], columns=['frequency', 'recency', 'T'])
        self.generate_new_data = lambda size=1: pareto_nbd_model(T, *params, size=size)

        self.predict = self.conditional_expected_number_of_purchases_up_to_time
        return self

    @staticmethod
    def _log_A_0(params, frequency, recency, age):

        r, alpha, s, beta = params

        min_of_alpha_beta, max_of_alpha_beta, t = (alpha, beta, r + frequency) if alpha < beta else (beta, alpha, s + 1)
        abs_alpha_beta = max_of_alpha_beta - min_of_alpha_beta

        rsf = r + s + frequency
        p_1, q_1 = special.hyp2f1(rsf, t, rsf + 1., abs_alpha_beta / (max_of_alpha_beta + recency)), (
            max_of_alpha_beta + recency)
        p_2, q_2 = special.hyp2f1(rsf, t, rsf + 1., abs_alpha_beta / (max_of_alpha_beta + age)), (
            max_of_alpha_beta + age)

        try:
            size = len(frequency)
            sign = np.ones(size)
        except TypeError:
            sign = 1

        return misc.logsumexp([log(p_1) + rsf * log(q_2), log(p_2) + rsf * log(q_1)], axis=0, b=[sign, -sign]) \
               - rsf * log(q_1 * q_2)

    @staticmethod
    def _negative_log_likelihood(params, frequency, recency, T, penalizer_coef):

        if npany(asarray(params) <= 0.):
            return np.inf

        r, alpha, s, beta = params
        x = frequency

        r_s_x = r + s + x

        A_1 = special.gammaln(r + x) - special.gammaln(r) + r * log(alpha) + s * log(beta)
        log_A_0 = ParetoNBDFitter._log_A_0(params, frequency, recency, T)

        A_2 = logaddexp(-(r + x) * log(alpha + T) - s * log(beta + T), log(s) + log_A_0 - log(r_s_x))

        penalizer_term = penalizer_coef * log(params).sum()
        return -(A_1 + A_2).sum() + penalizer_term

    def conditional_probability_alive(self, frequency, recency, T):
        """
        Compute the probability that a customer with history (frequency, recency, T) is currently
        alive. From http://brucehardie.com/notes/009/pareto_nbd_derivations_2005-11-05.pdf

        Parameters:
            frequency: a scalar: historical frequency of customer.
            recency: a scalar: historical recency of customer.
            T: a scalar: age of the customer.

        Returns: a scalar value representing a probability
        """
        x, t_x = frequency, recency
        r, alpha, s, beta = self._unload_params('r', 'alpha', 's', 'beta')

        A_0 = np.exp(self._log_A_0([r, alpha, s, beta], x, t_x, T))
        return 1. / (1. + (s / (r + s + x)) * (alpha + T) ** (r + x) * (beta + T) ** s * A_0)

    def conditional_probability_alive_matrix(self, max_frequency=None, max_recency=None):
        """
        Compute the probability alive matrix
        Parameters:
            max_frequency: the maximum frequency to plot. Default is max observed frequency.
            max_recency: the maximum recency to plot. This also determines the age of the customer.
                Default to max observed age.

        Returns a matrix of the form [t_x: historical recency, x: historical frequency]

        """

        max_frequency = max_frequency or int(self.data['frequency'].max())
        max_recency = max_recency or int(self.data['T'].max())

        Z = np.zeros((max_recency + 1, max_frequency + 1))
        for i, recency in enumerate(np.arange(max_recency + 1)):
            for j, frequency in enumerate(np.arange(max_frequency + 1)):
                Z[i, j] = self.conditional_probability_alive(frequency, recency, max_recency)

        return Z

    def conditional_expected_number_of_purchases_up_to_time(self, t, frequency, recency, T):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population, given they have purchase history (frequency, recency, T)

        Parameters:
            t: a scalar or array of times.
            frequency: a scalar: historical frequency of customer.
            recency: a scalar: historical recency of customer.
            T: a scalar: age of the customer.

        Returns: a scalar or array
        """
        x, t_x = frequency, recency
        params = self._unload_params('r', 'alpha', 's', 'beta')
        r, alpha, s, beta = params

        likelihood = exp(-self._negative_log_likelihood(params, x, t_x, T, 0))
        first_term = (special.gamma(r + x) / special.gamma(r)) * (alpha ** r * beta ** s) / (alpha + T) ** (r + x) / (
                                                                                                                         beta + T) ** s
        second_term = (r + x) * (beta + T) / (alpha + T) / (s - 1)
        third_term = 1 - ((beta + T) / (beta + T + t)) ** (s - 1)
        return first_term * second_term * third_term / likelihood

    def expected_number_of_purchases_up_to_time(self, t):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.

        Returns: a scalar or array
        """
        r, alpha, s, beta = self._unload_params('r', 'alpha', 's', 'beta')
        return self.static_expected_number_of_purchases_up_to_time(r, alpha, s, beta, t)

    @staticmethod
    def static_expected_number_of_purchases_up_to_time(r, a, s, b, t):
        r, alpha, s, beta = (r, a, s, b)
        first_term = r * beta / alpha / (s - 1)
        second_term = 1 - (beta / (beta + t)) ** (s - 1)
        return first_term * second_term

    def expected_number_of_purchases_up_to_time_error(self, t, C):
        """
        Calculate the error of expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.
            C: covariance matrix of parameters 'r', 'alpha', 's', 'beta'

        Returns: a scalar
        """
        if len(C) != 4 or len(C[0]) != 4:
            raise ValueError("Covariance matrix: wrong dimensions. Must be 4x4 symmetric.")

        r, alpha, s, beta = self._unload_params('r', 'alpha', 's', 'beta')
        E = self.expected_number_of_purchases_up_to_time(t)
        dEdr = E / r
        dEdalpha = E * (-1.0 / alpha)
        dEds = -E / (s - 1) + (r * beta) / (alpha * (s - 1)) * (
            -math.log(beta / (beta + t)) * (beta / (beta + t)) ** (s - 1))
        dEdbeta = E / beta + (r * beta) / (alpha * (s - 1)) * (
            (1 - s) * (beta / (beta + t)) ** (s - 2) * t / (beta + t) ** 2)

        Cov = np.matrix(C)
        dE = np.array([[dEdr], [dEdalpha], [dEds], [dEdbeta]])

        return math.sqrt(float(dE.transpose() * Cov * dE))


class BetaGeoFitter(BaseFitter):
    """

    Also known as the BG/NBD model. Based on [1], this model has the following assumptions:

    1) Each individual, i, has a hidden lambda_i and p_i parameter
    2) These come from a population wide Gamma and a Beta distribution respectively.
    3) Individuals purchases follow a Poisson process with rate lambda_i*t .
    4) After each purchase, an individual has a p_i probability of dieing (never buying again).

    [1] Fader, Peter S., Bruce G.S. Hardie, and Ka Lok Lee (2005a),
        "Counting Your Customers the Easy Way: An Alternative to the
        Pareto/NBD Model," Marketing Science, 24 (2), 275-84.

    """

    def __init__(self, penalizer_coef=0.):
        self.penalizer_coef = penalizer_coef

    def fit(self, frequency, recency, T, iterative_fitting=0, initial_params=None, verbose=False, N=None):
        """
        This methods fits the data to the BG/NBD model.

        Parameters:
            frequency: the frequency vector of customers' purchases (denoted x in literature).
            recency: the recency vector of customers' purchases (denoted t_x in literature).
            T: the vector of customers' age (time since first purchase)
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates.
            initial_params: set the initial parameters for the fitter.
            verbose: set to true to print out convergence diagnostics.


        Returns:
            self, with additional properties and methods like params_ and predict

        """
        frequency = asarray(frequency)
        recency = asarray(recency)
        T = asarray(T)
        _check_inputs(frequency, recency, T)

        self._scale = _scale_time(T)
        scaled_recency = recency * self._scale
        scaled_T = T * self._scale

        params, self._negative_log_likelihood_ = _fit(self._negative_log_likelihood,
                                                      [frequency, scaled_recency, scaled_T, self.penalizer_coef],
                                                      iterative_fitting,
                                                      initial_params,
                                                      4,
                                                      verbose)

        self.params_ = OrderedDict(zip(['r', 'alpha', 'a', 'b'], params))
        self.params_['alpha'] /= self._scale

        self.data = DataFrame(vconcat[frequency, recency, T], columns=['frequency', 'recency', 'T'])
        self.generate_new_data = lambda size=1: beta_geometric_nbd_model(T,
                                                                         *self._unload_params('r', 'alpha', 'a', 'b'),
                                                                         size=size)

        self.predict = self.conditional_expected_number_of_purchases_up_to_time
        return self

    @staticmethod
    def _negative_log_likelihood(params, frequency, recency, T, penalizer_coef):
        if npany(asarray(params) <= 0):
            return np.inf

        r, alpha, a, b = params

        A_1 = special.gammaln(r + frequency) - special.gammaln(r) + r * log(alpha)
        A_2 = special.gammaln(a + b) + special.gammaln(b + frequency) - special.gammaln(b) - special.gammaln(a + b + frequency)
        A_3 = -(r + frequency) * log(alpha + T)

        d = vconcat[ones_like(frequency), (frequency > 0)]
        A_4 = log(a) - log(b + frequency - 1) - (r + frequency) * log(recency + alpha)
        A_4[isnan(A_4) | isinf(A_4)] = 0
        penalizer_term = penalizer_coef * log(params).sum()
        return -(A_1 + A_2 + misc.logsumexp(vconcat[A_3, A_4], axis=1, b=d)).sum() + penalizer_term

    def expected_number_of_purchases_up_to_time(self, t):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.

        Returns: a scalar or array
        """
        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')
        hyp = special.hyp2f1(r, b, a + b - 1, t / (alpha + t))
        return (a + b - 1) / (a - 1) * (1 - hyp * (alpha / (alpha + t)) ** r)

    def conditional_expected_number_of_purchases_up_to_time(self, t, frequency, recency, T):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population, given they have purchase history (frequency, recency, T)

        Parameters:
            t: a scalar or array of times.
            frequency: a scalar: historical frequency of customer.
            recency: a scalar: historical recency of customer.
            T: a scalar: age of the customer.

        Returns: a scalar or array
        """
        x = frequency
        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')

        hyp_term = special.hyp2f1(r + x, b + x, a + b + x - 1, t / (alpha + T + t))
        first_term = (a + b + x - 1) / (a - 1)
        second_term = (1 - hyp_term * ((alpha + T) / (alpha + t + T)) ** (r + x))
        numerator = first_term * second_term

        denominator = 1 + (x > 0) * (a / (b + x - 1)) * ((alpha + T) / (alpha + recency)) ** (r + x)

        return numerator / denominator

    def conditional_probability_alive(self, frequency, recency, T):
        """
        Compute the probability that a customer with history (frequency, recency, T) is currently
        alive. From http://www.brucehardie.com/notes/021/palive_for_BGNBD.pdf

        Parameters:
            frequency: a scalar: historical frequency of customer.
            recency: a scalar: historical recency of customer.
            T: a scalar: age of the customer.

        Returns: a scalar

        """
        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')
        return 1. / (
            1 + (frequency > 0) * (a / (b + frequency - 1)) * ((alpha + T) / (alpha + recency)) ** (r + frequency))

    def conditional_probability_alive_matrix(self, max_frequency=None, max_recency=None):
        """
        Compute the probability alive matrix
        Parameters:
            max_frequency: the maximum frequency to plot. Default is max observed frequency.
            max_recency: the maximum recency to plot. This also determines the age of the customer.
                Default to max observed age.

        Returns a matrix of the form [t_x: historical recency, x: historical frequency]

        """

        max_frequency = max_frequency or int(self.data['frequency'].max())
        max_recency = max_recency or int(self.data['T'].max())

        Z = np.zeros((max_recency + 1, max_frequency + 1))
        for i, t_x in enumerate(np.arange(max_recency + 1)):
            for j, x in enumerate(np.arange(max_frequency + 1)):
                Z[i, j] = self.conditional_probability_alive(x, t_x, max_recency)

        return Z

    def probability_of_n_purchases_up_to_time(self, t, n):
        """
        Compute the probability of

        P( N(t) = n | model )

        where N(t) is the number of repeat purchases a customer makes in t units of time.
        """

        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')

        first_term = special.beta(a, b + n) / special.beta(a, b) * special.gamma(r + n) / special.gamma(
            r) / special.gamma(n + 1) * (alpha / (alpha + t)) ** r * (t / (alpha + t)) ** n
        if n > 0:
            finite_sum = np.sum(
                [special.gamma(r + j) / special.gamma(r) / special.gamma(j + 1) * (t / (alpha + t)) ** j for j in
                 range(0, n)])
            second_term = special.beta(a + 1, b + n - 1) / special.beta(a, b) * (
                1 - (alpha / (alpha + t)) ** r * finite_sum)
        else:
            second_term = 0
        return first_term + second_term


class ModifiedBetaGeoFitter(BetaGeoFitter):
    """
    Also known as the MBG/NBD model. Based on [1,2], this model has the following assumptions:
    1) Each individual, i, has a hidden lambda_i and p_i parameter
    2) These come from a population wide Gamma and a Beta distribution respectively.
    3) Individuals purchases follow a Poisson process with rate lambda_i*t .
    4) At the beginning of their lifetime and after each purchase, an individual has a
       p_i probability of dieing (never buying again).
    [1] Batislam, E.P., M. Denizel, A. Filiztekin (2007),
        "Empirical validation and comparison of models for customer base analysis,"
        International Journal of Research in Marketing, 24 (3), 201-209.
    [2] Wagner, U. and Hoppe D. (2008), "Erratum on the MBG/NBD Model," International Journal
        of Research in Marketing, 25 (3), 225-226.
    """

    def __init__(self, penalizer_coef=0.):
        super(self.__class__, self).__init__(penalizer_coef)

    def fit(self, frequency, recency, T, iterative_fitting=0, initial_params=None, verbose=False, N=None):
        """
        This methods fits the data to the MBG/NBD model.
        Parameters:
            frequency: the frequency vector of customers' purchases (denoted x in literature).
            recency: the recency vector of customers' purchases (denoted t_x in literature).
            T: the vector of customers' age (time since first purchase)
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates.
            initial_params: set the initial parameters for the fitter.
            verbose: set to true to print out convergence diagnostics.
        Returns:
            self, with additional properties and methods like params_ and predict
        """
        super(self.__class__, self).fit(frequency, recency, T, iterative_fitting, initial_params,
                                        verbose)  # although the partent method is called, this class's _negative_log_likelihood is referenced
        self.generate_new_data = lambda size=1: modified_beta_geometric_nbd_model(T, *self._unload_params('r', 'alpha',
                                                                                                          'a', 'b'),
                                                                                  size=size)  # this needs to be reassigned from the parent method
        return self

    @staticmethod
    def _negative_log_likelihood(params, frequency, recency, T, penalizer_coef):
        if npany(asarray(params) <= 0):
            return np.inf

        r, alpha, a, b = params

        A_1 = special.gammaln(r + frequency) - special.gammaln(r) + r * log(alpha)
        A_2 = special.gammaln(a + b) + special.gammaln(b + frequency + 1) - special.gammaln(b) - special.gammaln(
            a + b + frequency + 1)
        A_3 = -(r + frequency) * log(alpha + T)
        A_4 = log(a) - log(b + frequency) + (r + frequency) * (log(alpha + T) - log(alpha + recency))

        penalizer_term = penalizer_coef * log(params).sum()
        return -(A_1 + A_2 + A_3 + log(exp(A_4) + 1.)).sum() + penalizer_term

    def expected_number_of_purchases_up_to_time(self, t):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population.
        Parameters:
            t: a scalar or array of times.
        Returns: a scalar or array
        """
        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')
        hyp = special.hyp2f1(r, b + 1, a + b, t / (alpha + t))
        return b / (a - 1) * (1 - hyp * (alpha / (alpha + t)) ** r)

    def conditional_expected_number_of_purchases_up_to_time(self, t, frequency, recency, T):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population, given they have purchase history (frequency, recency, T)
        See Wagner, U. and Hoppe D. (2008).
        Parameters:
            t: a scalar or array of times.
            frequency: a scalar: historical frequency of customer.
            recency: a scalar: historical recency of customer.
            T: a scalar: age of the customer.
        Returns: a scalar or array
        """
        x = frequency
        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')

        hyp_term = special.hyp2f1(r + x, b + x + 1, a + b + x, t / (alpha + T + t))
        first_term = (a + b + x) / (a - 1)
        second_term = (1 - hyp_term * ((alpha + T) / (alpha + t + T)) ** (r + x))
        numerator = first_term * second_term

        denominator = 1 + (a / (b + x)) * ((alpha + T) / (alpha + recency)) ** (r + x)

        return numerator / denominator

    def conditional_probability_alive(self, frequency, recency, T):
        """
        Compute the probability that a customer with history (frequency, recency, T) is currently
        alive. From http://www.brucehardie.com/notes/021/palive_for_BGNBD.pdf
        Parameters:
            frequency: a scalar: historical frequency of customer.
            recency: a scalar: historical recency of customer.
            T: a scalar: age of the customer.
        Returns: a scalar
        """
        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')
        return 1. / (1 + (a / (b + frequency)) * ((alpha + T) / (alpha + recency)) ** (r + frequency))

    def conditional_probability_alive_matrix(self, max_frequency=None, max_recency=None):
        """
        Compute the probability alive matrix
        Parameters:
            max_frequency: the maximum frequency to plot. Default is max observed frequency.
            max_recency: the maximum recency to plot. This also determines the age of the customer.
                Default to max observed age.
        Returns a matrix of the form [t_x: historical recency, x: historical frequency]
        """
        return super(self.__class__, self).conditional_probability_alive_matrix(max_frequency, max_recency)

    def probability_of_n_purchases_up_to_time(self, t, n):
        """
        Compute the probability of
        P( N(t) = n | model )
        where N(t) is the number of repeat purchases a customer makes in t units of time.
        """

        r, alpha, a, b = self._unload_params('r', 'alpha', 'a', 'b')

        first_term = special.beta(a, b + n + 1) / special.beta(a, b) * special.gamma(r + n) / special.gamma(
            r) / special.gamma(n + 1) * (alpha / (alpha + t)) ** r * (t / (alpha + t)) ** n
        finite_sum = np.sum(
            [special.gamma(r + j) / special.gamma(r) / special.gamma(j + 1) * (t / (alpha + t)) ** j for j in
             range(0, n)])
        second_term = special.beta(a + 1, b + n) / special.beta(a, b) * (1 - (alpha / (alpha + t)) ** r * finite_sum)

        return first_term + second_term


class BGBBFitter(BaseFitter):
    """
    BG/BB discrete time model.

    Customer-Base Analysis in a Discrete-Time Noncontractual Setting
    Peter S. Fader
    Bruce G. S. Hardie
    Jen Shang
    """

    def __init__(self, penalizer_coef=0.):
        self.penalizer_coef = penalizer_coef

    @staticmethod
    def _negative_log_likelihood(params, frequency, recency, T, penalizer_coef, N=None, jac=False):
        """

        Args:
            params:
            frequency:
            recency:
            T:
            penalizer_coef:
            N:
            c_likelihood_lib:
            jac:        if true, returns also the gradient of the likelyhood

        Returns:

        """

        if npany(asarray(params) <= 0.):
            if jac:
                return np.inf, np.array([0, 0, 0, 0])
            return np.inf

        a, b, g, d = params
        x = frequency
        tx = recency

        denominator = special.beta(a, b) * special.beta(g, d)

        if isinstance(x, float) or isinstance(x, int):
            # x is a single number
            numerator = special.beta(a + x, b + T - x) * special.beta(g, d + T)
            numerator += np.sum(
                [special.beta(a + x, b + tx - x + i) * special.beta(g + 1, d + tx + i) for i in
                 range(int(T - tx - 1 + 1))])
        else:
            # x is a vector
            x = np.array(x)
            tx = np.array(tx)
            T = np.array(T)
            numerator = special.beta(a + x, b + T - x) * special.beta(g, d + T)

            max_i = (T - tx - 1).astype(int)
            for j in range(len(max_i)):
                xj = x[j]
                txj = tx[j]
                i = np.arange(max_i[j] + 1)  # all indexes
                numerator[j] += np.sum(special.beta(a + xj, b + txj - xj + i) * special.beta(g + 1, d + txj + i))

        Lj = numerator / denominator
        llj = np.log(Lj)  # this converts the terms in a no object on which you can call sum()
        penalizer_term = penalizer_coef * log(params).sum()

        if N is not None:
            ll = -(llj * N).sum()
        else:
            ll = -llj.sum()

        if jac is False:
            return ll + penalizer_term
        else:
            # calculate the gradient

            first_terms_j = np.array([special.psi(a + b) - special.psi(a),
                                      special.psi(a + b) - special.psi(b),
                                      special.psi(g + d) - special.psi(g),
                                      special.psi(g + d) - special.psi(d)
                                      ])

            BjBj = special.beta(a + x, b + T - x) * special.beta(g, d + T)

            if isinstance(x, float) or isinstance(x, int):
                # x is a single number
                i = np.arange(int(T - tx - 1) + 1)
                BiBi = special.beta(a + x, b + tx - x + i) * special.beta(g + 1, d + tx + i)
                sum_term_a = np.sum(BiBi * (special.psi(a + x) - special.psi(a + b + tx + i)))
                sum_term_b = np.sum(BiBi * (special.psi(b + tx - x + i) - special.psi(a + b + tx + i)))
                sum_term_g = np.sum(BiBi * (special.psi(g + 1) - special.psi(g + d + tx + i + 1)))
                sum_term_d = np.sum(BiBi * (special.psi(d + tx + i) - special.psi(g + d + tx + i + 1)))
            else:
                sum_term_a = np.array([0.0] * len(x))
                sum_term_b = np.array([0.0] * len(x))
                sum_term_g = np.array([0.0] * len(x))
                sum_term_d = np.array([0.0] * len(x))

                max_i = (T - tx - 1).astype(int)
                for j in range(len(max_i)):
                    xj = x[j]
                    txj = tx[j]
                    i = np.arange(max_i[j] + 1)  # all indexes
                    BjiBji = special.beta(a + xj, b + txj - xj + i) * special.beta(g + 1, d + txj + i)
                    sum_term_a[j] += np.sum(BjiBji * (special.psi(a + xj) - special.psi(a + b + txj + i)))
                    sum_term_b[j] += np.sum(BjiBji * (special.psi(b + txj - xj + i) - special.psi(a + b + txj + i)))
                    sum_term_g[j] += np.sum(BjiBji * (special.psi(g + 1) - special.psi(g + d + txj + i + 1)))
                    sum_term_d[j] += np.sum(BjiBji * (special.psi(d + txj + i) - special.psi(g + d + txj + i + 1)))

            dLjda = first_terms_j[0] * Lj + 1.0 / denominator * (
                BjBj * (special.psi(a + x) - special.psi(a + b + T)) + sum_term_a)
            dLjdb = first_terms_j[1] * Lj + 1.0 / denominator * (
                BjBj * (special.psi(b + T - x) - special.psi(a + b + T)) + sum_term_b)
            dLjdg = first_terms_j[2] * Lj + 1.0 / denominator * (
                BjBj * (special.psi(g) - special.psi(g + d + T)) + sum_term_g)
            dLjdd = first_terms_j[3] * Lj + 1.0 / denominator * (
                BjBj * (special.psi(d + T) - special.psi(g + d + T)) + sum_term_d)

            if N is not None:
                d_ll = np.array([-(dLjda / Lj * N).sum(), -(dLjdb / Lj * N).sum(), -(dLjdg / Lj * N).sum(),
                                 -(dLjdd / Lj * N).sum()])
            else:
                d_ll = np.array([-(dLjda / Lj).sum(), -(dLjdb / Lj).sum(), -(dLjdg / Lj).sum(),
                                 -(dLjdd / Lj).sum()])

            return ll, d_ll

    def fit(self, frequency, recency, T, iterative_fitting=0, initial_params=None, verbose=False, N=None, jac=False):
        """
        This methods fits the data to the BG/BB discrete-time model.

        Parameters:
            frequency: the frequency vector of customers' purchases (denoted x in literature).
            recency: the recency vector of customers' purchases (denoted t_x in literature).
            T: the vector of customers' age (time since first purchase)
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates.
            initial_params: set initial params for the iterative fitter.
            verbose: set to true to print out convergence diagnostics.
            N: in case of compressed data this parameter is a vector of the number of users with same recency, frequency, T

        Returns:
            self, with additional properties and methods like params_ and plot
        """
        frequency = asarray(frequency)
        recency = asarray(recency)
        T = asarray(T)
        _check_inputs(frequency, recency, T)

        if N is not None:  # in this case it means you're handling compressed data
            N = asarray(N)
            gen_t = reduce(lambda res, el: res + el, [[t] * n for t, n in zip(T, N)], [])
        else:
            gen_t = T
        params, self._negative_log_likelihood_ = _fit(self._negative_log_likelihood,
                                                      [frequency, recency, T, self.penalizer_coef, N, jac],
                                                      iterative_fitting,
                                                      initial_params,
                                                      4,
                                                      verbose,
                                                      jac)

        self.params_ = OrderedDict(zip(['alpha', 'beta', 'gamma', 'delta'], params))
        self.data = DataFrame(vconcat[frequency, recency, T], columns=['frequency', 'recency', 'T'])
        self.generate_new_data = lambda size=1, compressed=False, ts=gen_t: bgbb_model(ts, *params, size=size, compressed=compressed)

        # self.predict = self.conditional_expected_number_of_purchases_up_to_time   # TODO add these methods
        return self

    def expected_number_of_purchases_up_to_time(self, t):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.

        Returns: a scalar or array
        """
        a, b, g, d = self._unload_params('alpha', 'beta', 'gamma', 'delta')
        return BGBBFitter.static_expected_number_of_purchases_up_to_time(a, b, g, d, t)

    def limit_number_of_purchases(self):
        a, b, g, d = self._unload_params('alpha', 'beta', 'gamma', 'delta')
        return BGBBFitter.static_limit_number_of_purchases(a, b, g, d)

    @staticmethod
    def static_expected_number_of_purchases_up_to_time(a, b, g, d, t):
        return a / (a + b) * d / (g - 1) * (
            1.0 - (special.gamma(g + d) / special.gamma(1 + d)) / gamma_ratio(t + d + 1, g - 1))

    @staticmethod
    def static_limit_number_of_purchases(a, b, g, d):
        if g < 1:
            return np.infty
        return (a / (a + b)) * (d / (g - 1))

    def expected_number_of_purchases_up_to_time_error(self, t, C):
        """
        Calculate the error of expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.
            C: covariance matrix of parameters 'alpha', 'beta', 'gamma', 'delta'

        Returns: a scalar
        """
        a, b, g, d = self._unload_params('alpha', 'beta', 'gamma', 'delta')
        return BGBBFitter.static_expected_number_of_purchases_up_to_time_error(a, b, g, d, t, C)

    @staticmethod
    def static_expected_number_of_purchases_up_to_time_error(a, b, g, d, t, C):

        if len(C) != 4 or len(C[0]) != 4:
            raise ValueError("Covariance matrix: wrong dimensions. Must be 4x4 symmetric.")

        E = BGBBFitter.static_expected_number_of_purchases_up_to_time(a, b, g, d, t)

        R = a / (a + b) * d / (g - 1) * (
            - (special.gamma(g + d) / special.gamma(1 + d)) / gamma_ratio(t + d + 1, g - 1))

        dEda = b / (a + b) * E
        dEdb = - 1.0 / (a + b) * E

        dEdg = - E / (g - 1) + R * (special.psi(g + d) - special.psi(g + d + t))
        dEdd = E / d + R * (special.psi(g + d) - special.psi(g + d + t) - special.psi(1 + d) + special.psi(1 + d + t))

        Cov = np.matrix(C)
        dE = np.array([[dEda], [dEdb], [dEdg], [dEdd]])

        return math.sqrt(float(dE.transpose() * Cov * dE))

    def probability_of_n_purchases_up_to_time(self, t, n):
        """
        Compute the probability of

        P( N(t) = n | model )

        where N(t) is the number of repeat purchases a customer makes in t units of time.
        """
        a, b, g, d = self._unload_params('alpha', 'beta', 'gamma', 'delta')

        return BGBBFitter.static_probability_of_n_purchases_up_to_time(a, b, g, d, t, n)

    @staticmethod
    def static_probability_of_n_purchases_up_to_time(a, b, g, d, t, n):
        if not (isinstance(n, int) and isinstance(t, int)):
            raise TypeError("t and n must be integers")

        common_factor = 1.0 / special.beta(a, b) * 1.0 / special.beta(g, d)

        first_term = special.binom(t, n) * special.beta(a + n, b + t - n) * special.beta(g, d + t)
        second_term = np.sum(
            [special.binom(i, n) * special.beta(a + n, b + i - n) * special.beta(g + 1, d + i) for i in
             range(n, int(t - 1 + 1))])

        return common_factor * (first_term + second_term)

    @staticmethod
    def static_probability_alive_next_step(a, b, g, d, x, t_x, n):
        if not (isinstance(x, int) and isinstance(t_x, int)):
            raise TypeError("t_x and x and n must be integers")

        L = np.exp(-BGBBFitter._negative_log_likelihood((a, b, g, d), x, t_x, n, penalizer_coef=0.0))

        return B(a + x, b + n - x) / B(a, b) * B(g, d + n + 1) / B(g, d) * 1.0 / L


class BGBBBGFitter(BaseFitter):
    """
        BG/BB/BG discrete time model with session and conversion.

        EM as extension of
        Customer-Base Analysis in a Discrete-Time Noncontractual Setting
        Peter S. Fader
        Bruce G. S. Hardie
        Jen Shang
        """

    def __init__(self, penalizer_coef=0.):
        self.penalizer_coef = penalizer_coef
        self.params_ = None

    @staticmethod
    def _negative_log_likelihood(params, frequency, recency, T, frequency_before_conversion, penalizer_coef, N=None):

        if npany(asarray(params) <= 0.):
            return np.inf

        a, b, g, d, e, z = params
        xc = frequency_before_conversion
        x = frequency

        if isinstance(xc, float) or isinstance(xc, int):
            pass
        else:
            # xp is a vector
            x = np.array(x)
            xc = np.array(xc)

        mask = x >= xc
        purchase_term = special.beta(e + mask, z + xc) / special.beta(e, z)

        ll_vector = np.log(purchase_term)  # this converts the terms in a no object on which you can call sum()

        if N is not None:
            ll_purchases = -(ll_vector * N).sum()
        else:
            ll_purchases = -ll_vector.sum()

        sub_params = a, b, g, d
        return ll_purchases + BGBBFitter._negative_log_likelihood(sub_params, frequency, recency, T, penalizer_coef, N)

    def fit(self, frequency, recency, T, frequency_before_conversion, iterative_fitting=0, initial_params=None,
            verbose=False,
            N=None):
        """
        This methods fits the data to the BG/BB/BG discrete-time model.

        Parameters:
            frequency: the frequency vector of customers' sessions (denoted x in literature).
            recency: the recency vector of customers' sessions (denoted t_x in literature).
            T: the vector of customers' age (time since first session)
            frequency_before_conversion: the frequency vector of customers' purchases (can go from 0 to f).
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates.
            initial_params: set initial params for the iterative fitter.
            verbose: set to true to print out convergence diagnostics.
            N: in case of compressed data this parameter is a vector of the number of users with same recency, frequency,T

        Returns:
            self, with additional properties and methods like params_ and plot
        """

        frequency = asarray(frequency)
        recency = asarray(recency)
        T = asarray(T)
        frequency_before_conversion = asarray(frequency_before_conversion)
        _check_inputs(frequency, recency, T, N=N, frequency_before_conversion=frequency_before_conversion)
        if N is not None:  # in this case it means you're handling compressed data
            N = asarray(N)
            gen_t = reduce(lambda res, el: res + el, [[t] * n for t, n in zip(T, N)], [])
        else:
            gen_t = T
        params, self._negative_log_likelihood_ = _fit(self._negative_log_likelihood,
                                                      [frequency, recency, T, frequency_before_conversion,
                                                       self.penalizer_coef, N],
                                                      iterative_fitting,
                                                      initial_params,
                                                      6,
                                                      verbose)

        self.params_ = OrderedDict(zip(['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta'], params))
        self.data = DataFrame(vconcat[frequency, recency, T, frequency_before_conversion],
                              columns=['frequency', 'recency', 'T', 'frequency_purchases'])
        self.generate_new_data = lambda size=1, compressed=False, ts=gen_t: bgbbbg_model(ts, *params, size=size, compressed=compressed)

        return self

    def expected_probability_of_converting_at_time(self, t):

        a, b, g, d, e, z = self._unload_params('alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta')

        if t == 0:
            return B(e + 1, z) / B(e, z)

        alive_coefficient = B(g, d + t) / (B(a, b) * B(g, d) * B(e, z))
        summation = sum([ncr(t - 1, k) * (-1) ** k * B(a + k + 1, b) * B(e + k + 1, z + 1) for k in range(t)])

        return alive_coefficient * summation

    def expected_probability_of_converting_at_time_error(self, t, params_list):
        initial_params = self.params_.copy()
        values = []
        for params in params_list:
            self.params_ = {'alpha': params[0], 'beta': params[1], 'gamma': params[2], 'delta': params[3],
                            'epsilon': params[4], 'zeta': params[5]}
            value = self.expected_probability_of_converting_at_time(t)
            values.append(value)
        error = np.std(values)
        self.params_ = initial_params
        return error

    def expected_probability_of_converting_within_time(self, t):
        return sum([self.expected_probability_of_converting_at_time(ti) for ti in range(t + 1)])

    def expected_probability_of_converting_within_time_error(self, t, params_list):
        initial_params = self.params_.copy()
        values = []
        for params in params_list:
            self.params_ = {'alpha': params[0], 'beta': params[1], 'gamma': params[2], 'delta': params[3],
                            'epsilon': params[4], 'zeta': params[5]}
            value = self.expected_probability_of_converting_within_time(t)
            values.append(value)
        error = np.std(values)
        self.params_ = initial_params
        return error


class BGBBBGExtFitter(BaseFitter):
    """
        BG/BB/BG discrete time model with session and conversion.

        EM as extension of
        Customer-Base Analysis in a Discrete-Time Noncontractual Setting
        Peter S. Fader
        Bruce G. S. Hardie
        Jen Shang
        """

    def __init__(self, penalizer_coef=0.):
        self.penalizer_coef = penalizer_coef
        self.params_ = None

    @staticmethod
    def _negative_log_likelihood(params, frequency, recency, T, frequency_before_conversion, penalizer_coef, N=None):

        if npany(asarray(params) <= 0.):
            return np.inf

        a, b, g, d, e, z, c0 = params
        if c0 >= 1:
            return np.inf
        xc = frequency_before_conversion
        x = frequency

        if isinstance(xc, float) or isinstance(xc, int):
            pass
        else:
            # xp is a vector
            x = np.array(x)
            xc = np.array(xc)

        mask = x >= xc
        mask2 = xc == 0
        mask3 = xc != 0
        purchase_term = c0 * mask2 + (1 - c0) * (special.beta(e + mask, z + xc - 1) / special.beta(e, z)) * mask3

        ll_vector = np.log(purchase_term)  # this converts the terms in a no object on which you can call sum()

        if N is not None:
            ll_purchases = -(ll_vector * N).sum()
        else:
            ll_purchases = -ll_vector.sum()

        sub_params = a, b, g, d
        return ll_purchases + BGBBFitter._negative_log_likelihood(sub_params, frequency, recency, T, penalizer_coef, N)

    def fit(self, frequency, recency, T, frequency_before_conversion, iterative_fitting=0, initial_params=None,
            verbose=False,
            N=None):
        """
        This methods fits the data to the BG/BB/BG discrete-time model.

        Parameters:
            frequency: the frequency vector of customers' sessions (denoted x in literature).
            recency: the recency vector of customers' sessions (denoted t_x in literature).
            T: the vector of customers' age (time since first session)
            frequency_before_conversion: the frequency vector of customers' purchases (can go from 0 to f).
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates.
            initial_params: set initial params for the iterative fitter.
            verbose: set to true to print out convergence diagnostics.
            N: in case of compressed data this parameter is a vector of the number of users with same recency, frequency,T

        Returns:
            self, with additional properties and methods like params_ and plot
        """

        frequency = asarray(frequency)
        recency = asarray(recency)
        T = asarray(T)
        frequency_before_conversion = asarray(frequency_before_conversion)
        _check_inputs(frequency, recency, T, N=N, frequency_before_conversion=frequency_before_conversion)
        if N is not None:  # in this case it means you're handling compressed data
            N = asarray(N)
            gen_t = reduce(lambda res, el: res + el, [[t] * n for t, n in zip(T, N)], [])
        else:
            gen_t = T
        params, self._negative_log_likelihood_ = _fit(self._negative_log_likelihood,
                                                      [frequency, recency, T, frequency_before_conversion,
                                                       self.penalizer_coef, N],
                                                      iterative_fitting,
                                                      initial_params,
                                                      7,
                                                      verbose)

        self.params_ = OrderedDict(zip(['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'c0'], params))
        self.data = DataFrame(vconcat[frequency, recency, T, frequency_before_conversion],
                              columns=['frequency', 'recency', 'T', 'frequency_before_conversion'])
        self.generate_new_data = lambda size=1, compressed=False, ts=gen_t: bgbbbgext_model(ts, *params, size=size, compressed=compressed)
        return self

    def expected_probability_of_converting_at_time(self, t):
        a, b, g, d, e, z, c0 = self._unload_params('alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'c0')
        return BGBBBGExtFitter.static_regularized_expected_probability_of_converting_at_time(a, b, g, d, e, z, c0, t)

    def _straight_expected_probability_of_converting_at_time(self, t):
        a, b, g, d, e, z, c0 = self._unload_params('alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'c0')
        return BGBBBGExtFitter.static_expected_probability_of_converting_at_time(a, b, g, d, e, z, c0, t)

    @staticmethod
    def static_regularized_expected_probability_of_converting_at_time(a, b, g, d, e, z, c0, t):

        value = BGBBBGExtFitter.static_expected_probability_of_converting_at_time(a, b, g, d, e, z, c0, t)
        if t > 1:
            prev_value = BGBBBGExtFitter.static_expected_probability_of_converting_at_time(a, b, g, d, e, z, c0, t - 1)

            if value < 0.0 or value > prev_value or value < 0.000001 or value > 1.0:
                return 0.0
        return value

    @staticmethod
    def static_expected_probability_of_converting_at_time(a, b, g, d, e, z, c0, t):

        if t == 0:
            return c0

        alive_coefficient = B(g, d + t) / (B(a, b) * B(g, d) * B(e, z))
        summation = (1 - c0) * sum([ncr(t - 1, k) * (-1) ** k * B(a + k + 1, b) * B(e + k + 1, z) for k in range(t)])

        return alive_coefficient * summation

    def expected_probability_of_converting_at_time_error(self, t, params_list):
        initial_params = self.params_.copy()
        values = []
        for params in params_list:
            self.params_ = {'alpha': params[0], 'beta': params[1], 'gamma': params[2], 'delta': params[3],
                            'epsilon': params[4], 'zeta': params[5], 'c0': params[6]}
            value = self.expected_probability_of_converting_at_time(t)
            values.append(value)
        error = np.std(values)
        self.params_ = initial_params
        if math.isnan(error) or error > 1.0:
            error = 1.0
        return error

    def expected_probability_of_converting_within_time(self, t):
        return sum([self.expected_probability_of_converting_at_time(ti) for ti in range(t + 1)])

    @staticmethod
    def static_expected_probability_of_converting_within_time(a, b, g, d, e, z, c0, t):
        return sum(
            [BGBBBGExtFitter.static_regularized_expected_probability_of_converting_at_time(a, b, g, d, e, z, c0, ti) \
             for ti in range(t + 1)])

    def expected_probability_of_converting_within_time_error(self, t, params_list):
        initial_params = self.params_.copy()
        values = []
        for params in params_list:
            self.params_ = {'alpha': params[0], 'beta': params[1], 'gamma': params[2], 'delta': params[3],
                            'epsilon': params[4], 'zeta': params[5], 'c0': params[6]}
            value = self.expected_probability_of_converting_within_time(t)
            values.append(value)
        error = np.std(values)
        self.params_ = initial_params
        if math.isnan(error) or error > 1.0:
            error = 1.0
        return error

    def expected_number_of_sessions_up_to_time(self, t):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.

        Returns: a scalar or array
        """
        a, b, g, d = self._unload_params('alpha', 'beta', 'gamma', 'delta')
        return BGBBBGExtFitter.static_expected_number_of_sessions_up_to_time(a, b, g, d, t)

    def expected_number_of_sessions_up_to_time_error(self, t, C):
        """
        Calculate the error of expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.
            C: covariance matrix of parameters 'alpha', 'beta', 'gamma', 'delta'

        Returns: a scalar
        """
        a, b, g, d = self._unload_params('alpha', 'beta', 'gamma', 'delta')
        return BGBBFitter.static_expected_number_of_purchases_up_to_time_error(a, b, g, d, t, C)

    @staticmethod
    def static_expected_number_of_sessions_up_to_time(a, b, g, d, t):
        return BGBBFitter.static_expected_number_of_purchases_up_to_time(a, b, g, d, t)

    def probability_of_n_sessions_up_to_time(self, t, n):
        a, b, g, d = self._unload_params('alpha', 'beta', 'gamma', 'delta')
        return BGBBBGExtFitter.static_probability_of_n_sessions_up_to_time(a, b, g, d, t, n)

    @staticmethod
    def static_probability_of_n_sessions_up_to_time(a, b, g, d, t, n):
        return BGBBFitter.static_probability_of_n_purchases_up_to_time(a, b, g, d, t, n)


class BGFitter(BaseFitter):
    """
    BG discrete time model.
    Used to model contractual settings as apps with subscriptions.
    The probability of a user to churn at every time step is beta distributed.
    """

    def __init__(self, penalizer_coef=0.):
        self.penalizer_coef = penalizer_coef

    @staticmethod
    def _negative_log_likelihood(params, frequency, T, penalizer_coef, N=None):
        """
        """

        a = params[0]
        b = params[1]
        if npany(asarray([a, b]) <= 0.):
            return np.inf

        x = frequency
        if isinstance(x, float) or isinstance(x, int):
            Ntot = 1
        else:
            Ntot = len(x)
        if N is not None:
            Ntot = np.array(N).sum()

        if isinstance(x, float) or isinstance(x, int):
            # x is a single number
            numerator = 0
            if x < T:
                numerator += special.beta(a + 1, b + x)
            elif x == T:
                numerator += special.beta(a, b + x)

        else:
            # x is a vector
            x = np.array(x)
            T = np.array(T)
            dead_ones_to_add = (x < T).astype(int)
            numerator = special.beta(a + dead_ones_to_add, b + x)

        Lj = numerator
        llj = np.log(Lj)  # this converts the terms in a np object on which you can call sum()
        penalizer_term = penalizer_coef * log(params).sum()

        if N is not None:
            ll = -(llj * N).sum()
        else:
            ll = -llj.sum()

        return ll + Ntot * log(special.beta(a, b)) + penalizer_term

    def fit(self, frequency, T, iterative_fitting=0, initial_params=None, verbose=False, N=None):
        """
        This methods fits the data to the BG discrete-time model.

        Parameters:
            frequency: the frequency vector of customers' purchases (denoted x in literature).
            T: the vector of customers' age (time since first purchase)
            iterative_fitting: perform `iterative_fitting` additional fits to find the best
                parameters for the model. Setting to 0 will improve performances but possibly
                hurt estimates.
            initial_params: set initial params for the iterative fitter.
            verbose: set to true to print out convergence diagnostics.
            N: in case of compressed data this parameter is a vector of the number of users with same recency, frequency, T

        Returns:
            self, with additional properties and methods like params_ and plot
        """
        frequency = asarray(frequency)
        T = asarray(T)

        if np.any(frequency > T):
            raise ValueError(
                """Some values in frequency vector are larger than T vector. This is impossible according to the model.""")
        if np.any(frequency < 0):
            raise ValueError("""Some values in frequency vector are < 0""")
        if np.any(T < 0):
            raise ValueError("""Some values in T vector are < 0""")

        if N is not None:  # in this case it means you're handling compressed data
            N = asarray(N)
            gen_t = reduce(lambda res, el: res + el, [[t] * n for t, n in zip(T, N)], [])
        else:
            gen_t = T
        params, self._negative_log_likelihood_ = _fit(self._negative_log_likelihood,
                                                      [frequency, T, self.penalizer_coef, N],
                                                      iterative_fitting,
                                                      initial_params,
                                                      2,
                                                      verbose)

        self.params_ = OrderedDict(zip(['alpha', 'beta'], params))
        self.data = DataFrame(vconcat[frequency, T], columns=['frequency', 'T'])

        self.generate_new_data = lambda size=1, compressed=False, ts=gen_t: bgext_model(ts, *params, size=size, compressed=compressed)

        return self

    def expected_number_of_purchases_up_to_time(self, t):
        """
        Calculate the expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.

        Returns: a scalar or array
        """
        a, b = self._unload_params('alpha', 'beta')
        return BGFitter.static_expected_number_of_purchases_up_to_time(a, b, t)

    @staticmethod
    def static_expected_number_of_purchases_up_to_time(a, b, t):
        if t == 0:
            return 0
        elif t == 1:
            return special.beta(a, b + 1) / special.beta(a, b)
        den = special.beta(a, b)
        num = t * special.beta(a, b + t) + special.beta(a - 1, b + 1) - special.beta(a - 1, b + t) \
              - (t - 1) * special.beta(a, b + t)
        return num / den

    def expected_number_of_purchases_up_to_time_error(self, t, C):
        """
        Calculate the error of expected number of repeat purchases up to time t for a randomly choose individual from
        the population.

        Parameters:
            t: a scalar or array of times.
            C: covariance matrix of parameters 'alpha', 'beta', 'gamma', 'delta'

        Returns: a scalar
        """
        a, b = self._unload_params('alpha', 'beta')
        return BGFitter.static_expected_number_of_purchases_up_to_time_error(a, b, t, C)

    @staticmethod
    def static_expected_number_of_purchases_up_to_time_error(a, b, t, C):

        if t == 0:
            return 0

        if len(C) != 2 or len(C[0]) != 2:
            raise ValueError("Covariance matrix: wrong dimensions. Must be 2x2 symmetric.")

        def dx(x, y):
            return special.beta(x, y) * (special.psi(x) - special.psi(x + y))

        def dy(x, y):
            return special.beta(x, y) * (special.psi(y) - special.psi(x + y))

        B = special.beta(a, b)
        E = BGFitter.static_expected_number_of_purchases_up_to_time(a, b, t) * B

        dEda = (t * dx(a, b + t) + dx(a - 1, b + 1) - dx(a - 1, b + t) - (t - 1) * dx(a, b + t)) / B - E / (
            B ** 2) * dx(a, b)
        dEdb = (t * dy(a, b + t) + dy(a - 1, b + 1) - dy(a - 1, b + t) - (t - 1) * dy(a, b + t)) / B - E / (
            B ** 2) * dy(a, b)

        Cov = np.matrix(C)
        dE = np.array([[dEda], [dEdb]])

        return math.sqrt(float(dE.transpose() * Cov * dE))

    def probability_of_n_purchases_up_to_time(self, t, n):
        """
        Compute the probability of

        P( N(t) = n | model )

        where N(t) is the number of repeat purchases a customer makes in t units of time.
        """
        a, b = self._unload_params('alpha', 'beta')

        return BGFitter.static_probability_of_n_purchases_up_to_time(a, b, t, n)

    @staticmethod
    def static_probability_of_n_purchases_up_to_time(a, b, t, n):
        if not (isinstance(n, int) and isinstance(t, int)):
            raise TypeError("t and n must be integers")

        den = special.beta(a, b)
        if t < n:
            raise ValueError("t must be >= n")
        elif n == 0:
            num = special.beta(a + 1, b)
        elif n < t:
            num = special.beta(a + 1, b + n)
        else:
            num = special.beta(a, b + n)

        return num / den
