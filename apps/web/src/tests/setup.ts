import '@testing-library/jest-dom';

// jsdom does not implement scrollIntoView, which Chat calls to autoscroll.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
