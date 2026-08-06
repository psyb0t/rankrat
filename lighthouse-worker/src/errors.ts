export class RequestTooLargeError extends Error {
  public constructor() {
    super("request body exceeds the allowed size");
    this.name = "RequestTooLargeError";
  }
}
