/* Trusted calculation-only worker. No model code, chart rendering or navigation. */
'use strict';
const {getIndicatorClass} = require('./native-calculations.cjs');
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  input += chunk;
  if (input.length > 2_000_000) process.exit(2);
});
process.stdin.on('end', () => {
  try {
    const request = JSON.parse(input);
    const Class = getIndicatorClass(request.name);
    if (!Class || !Array.isArray(request.candles) || request.candles.length > 5000) throw Error('invalid request');
    const indicator = new Class();
    if (request.parameters?.length) {
      indicator.calcParams = request.parameters;
      if (indicator.regenerateFigures) indicator.figures = indicator.regenerateFigures(request.parameters);
    }
    const values = indicator.calc(request.candles, indicator);
    if (!Array.isArray(values) || values.length !== request.candles.length) throw Error('invalid output');
    process.stdout.write(JSON.stringify({values, figures: indicator.figures.map(({key,type,title}) => ({key,type,title}))}));
  } catch { process.stderr.write('Chart indicator calculation failed'); process.exitCode = 1; }
});
