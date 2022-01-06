FAST_AR_TRENDING_SCRIPT = """
double softenLBC(double lbc) { return (Math.pow(lbc, 1.0 / 3.0)); }

double logsumexp(double x, double y)
{
    double top;
    if(x > y)
        top = x;
    else
        top = y;
    double result = top + Math.log(Math.exp(x-top) + Math.exp(y-top));
    return(result);
}

double logdiffexp(double big, double small)
{
    return big + Math.log(1.0 - Math.exp(small - big));
}

double squash(double x)
{
    if(x < 0.0)
return -Math.log(1.0 - x);
    else
return Math.log(x + 1.0);
}

double unsquash(double x)
{
    if(x < 0.0)
        return 1.0 - Math.exp(-x);
    else
        return Math.exp(x) - 1.0;
}

double log_to_squash(double x)
{
    return logsumexp(x, 0.0);
}

double squash_to_log(double x)
{
    //assert x > 0.0;
    return logdiffexp(x, 0.0);
}

double squashed_add(double x, double y)
{
    // squash(unsquash(x) + unsquash(y)) but avoiding overflow.
    // Cases where the signs are the same
    if (x < 0.0 && y < 0.0)
        return -logsumexp(-x, logdiffexp(-y, 0.0));
    if (x >= 0.0 && y >= 0.0)
        return logsumexp(x, logdiffexp(y, 0.0));
    // Where the signs differ
    if (x >= 0.0 && y < 0.0)
        if (Math.abs(x) >= Math.abs(y))
            return logsumexp(0.0, logdiffexp(x, -y));
        else
            return -logsumexp(0.0, logdiffexp(-y, x));
    if (x < 0.0 && y >= 0.0)
    {
        // Addition is commutative, hooray for new math
        return squashed_add(y, x);
    }
    return 0.0;
}

double squashed_multiply(double x, double y)
{
    // squash(unsquash(x)*unsquash(y)) but avoiding overflow.
    int sign;
    if(x*y >= 0.0)
sign = 1;
    else
sign = -1;
    return sign*logsumexp(squash_to_log(Math.abs(x))
    + squash_to_log(Math.abs(y)), 0.0);
}

// Squashed inflated units
double inflateUnits(int height) {
    double timescale = 576.0; // Half life of 400 = e-folding time of a day
      // by coincidence, so may as well go with it
    return log_to_squash(height / timescale);
}

double spikePower(double newAmount) {
    if (newAmount < 50.0) {
        return(0.5);
    } else if (newAmount < 85.0) {
        return(newAmount / 100.0);
    } else {
        return(0.85);
    }
}

double spikeMass(double oldAmount, double newAmount) {
    double softenedChange = softenLBC(Math.abs(newAmount - oldAmount));
    double changeInSoftened = Math.abs(softenLBC(newAmount) - softenLBC(oldAmount));
    double power = spikePower(newAmount);
    if (oldAmount > newAmount) {
        -1.0 * Math.pow(changeInSoftened, power) * Math.pow(softenedChange, 1.0 - power)
    } else {
        Math.pow(changeInSoftened, power) * Math.pow(softenedChange, 1.0 - power)
    }
}

for (i in params.src.changes) {
    double units = inflateUnits(i.height);
    if (ctx._source.trending_score == null) {
        ctx._source.trending_score = 0.0;
    }
    double bigSpike = squashed_multiply(units, squash(spikeMass(i.prev_amount, i.new_amount)));
    ctx._source.trending_score = squashed_add(ctx._source.trending_score, bigSpike);
}
"""
